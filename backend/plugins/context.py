"""
plugins/context.py
PluginContext — 注入给每个插件的主程序 API 对象。
插件通过 self.ctx 调用 ingest_file()、log()、register_for_stage() 等，不经过 HTTP 路由。
"""

from __future__ import annotations

import secrets
import shutil
import threading
from pathlib import Path
from typing import Optional

from app_logging import logger
from plugins.base import TrackMeta

# 序列化插件发起的 DB 写入（SQLite 单写者约束）
# 与上传端点的 asyncio.Lock 独立，但两者都保证串行写入
_write_lock = threading.Lock()


class PluginContext:
    """
    插件运行时 API。由 loader 在 setup() 时注入给插件实例。

    插件不应直接持有 DB session 或 Model 实例，
    所有库操作都通过本对象的方法进行。
    """

    def __init__(self, plugin_id: str, config: dict):
        self.config = config
        self.data_dir = (
            Path(__file__).parent.parent.parent / "data" / "plugins" / plugin_id
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._plugin_id = plugin_id

    # ── 日志 ──────────────────────────────────────────────────

    def log(self, level: str, msg: str) -> None:
        getattr(logger, level.lower(), logger.info)(
            "[plugin:%s] %s", self._plugin_id, msg
        )

    # ── 流水线注册 ────────────────────────────────────────────

    def register_for_stage(self, stage: str, callback) -> None:
        """
        在指定流水线阶段注册回调，仅应在 setup() 自检通过后调用。

        stage:    流水线阶段 ID，有效值：
                  "parse_upload"       — 上传时清洗文件名/标签
                  "fingerprint_lookup" — 指纹写入后查外部元数据库
                  "info_lookup"        — 通过标题/艺人名查外部元数据库
        callback: 对应的异步方法（如 self.parse_upload）

        同一 plugin+stage 重复注册时覆盖旧条目（reload 安全）。
        """
        from services.pipeline import get_registry
        get_registry().register(self._plugin_id, stage, callback)

    # ── 音乐库写入 ────────────────────────────────────────────

    def ingest_file(self, file_path: Path, meta: TrackMeta) -> dict:
        """
        将本地音频文件导入曲库。

        流程（复用 upload.py 的处理逻辑，不走 HTTP）：
        1. 复制到 RESOURCE_DIR（随机文件名）
        2. 调用 _process_uploaded_file_sync（无损转码、PCM hash、标签解析）
        3. 音频 hash 去重
        4. 写入 DB（threading.Lock 串行化）

        meta 提供的值优先于文件标签；title/artist 为空时回退到标签或 fallback 值。

        返回 {"status": "added"|"duplicate", "track_id": N, "title": ...}
        """
        # 延迟导入，避免循环依赖
        from routers.upload import (
            _apply_cover,
            _get_or_create_album,
            _get_or_create_artist,
            _process_uploaded_file_sync,
            enqueue_fingerprint_task,
            RESOURCE_DIR,
            SUPPORTED_EXTS,
        )
        from services.artist_names import (
            add_track_featured_artists,
            artist_names_from_tag_dict,
            dedupe_artist_names,
        )
        from database import SessionLocal
        import models

        suffix = file_path.suffix.lower()
        if suffix not in SUPPORTED_EXTS:
            raise ValueError(f"不支持的文件格式: {suffix}")

        # 复制到 resource 目录；audio_hash 会在处理后统一计算并用于去重。
        RESOURCE_DIR.mkdir(exist_ok=True)
        dest = RESOURCE_DIR / (secrets.token_hex(24) + suffix)
        if not dest.exists():
            shutil.copy2(file_path, dest)

        # 线程池处理：无损转码 + PCM hash + 时长 + 标签
        result = _process_uploaded_file_sync(dest, file_path.name)
        final_suffix = result.get("final_suffix", suffix)
        file_key = dest.stem + final_suffix
        audio_hash: Optional[bytes] = result["audio_hash"]

        db = SessionLocal()
        try:
            with _write_lock:
                # 音频 hash 去重（格式无关）
                if audio_hash:
                    dup = (
                        db.query(models.Track)
                        .filter(models.Track.audio_hash == audio_hash)
                        .first()
                    )
                    if dup:
                        # 本次导入产生的资源文件不再需要。
                        (RESOURCE_DIR / file_key).unlink(missing_ok=True)
                        self.log("info", f"重复跳过 track_id={dup.id}")
                        return {"status": "duplicate", "track_id": dup.id, "title": dup.title}

                # 元数据优先级：插件提供 > 文件标签 > fallback
                tag = result.get("tag_parsed")
                def _one_embedded_title(raw):
                    if raw is None:
                        return ""
                    if isinstance(raw, (list, tuple)) and raw:
                        raw = raw[0]
                    return str(raw).strip()

                t_meta = (meta.title or "").strip()
                t_tag = _one_embedded_title(tag.get("title") if tag else None)
                title = t_meta or t_tag
                names = dedupe_artist_names([str(x) for x in (meta.artists or [])])
                if not names and meta.artist:
                    names = dedupe_artist_names([meta.artist])
                if not names and tag:
                    names = artist_names_from_tag_dict(tag)
                if not names:
                    names = ["未知艺人"]

                album_title = meta.album or (tag.get("album") if tag else None)
                release_date = meta.release_date or (tag.get("release_date") if tag else None)
                track_number = meta.track_number or (tag.get("track_number") if tag else 0)
                duration = meta.duration_sec or result.get("duration", 0)
                lyrics = (tag.get("lyrics") if tag else None) or None

                primary = _get_or_create_artist(db, names[0])
                album_obj = None
                if album_title:
                    album_obj = _get_or_create_album(db, album_title, primary, release_date)

                track = models.Track(
                    title=title,
                    artist_id=primary.id,
                    album_id=album_obj.id if album_obj else None,
                    duration_sec=duration,
                    track_number=track_number,
                    lyrics=lyrics,
                    stream_url=f"/resource/{file_key}",
                    audio_hash=audio_hash,
                )
                _apply_cover(tag, album_obj, track)
                db.add(track)
                db.flush()
                add_track_featured_artists(db, track.id, names, _get_or_create_artist)
                enqueue_fingerprint_task(db, track.id)
                db.commit()
                db.refresh(track)
                self.log("info", f"已入库 track_id={track.id} title={track.title!r}")
                return {"status": "added", "track_id": track.id, "title": track.title}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
