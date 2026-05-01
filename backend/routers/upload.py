"""
routers/upload.py

三步上传 API：
  POST /tracks/upload-file            — 存文件 → 入队 → 立即返回 {job_id}
  GET  /tracks/upload-status/{job_id} — 轮询任务状态（pending/processing/done/error）
  POST /tracks/create                 — asyncio.Lock 串行写库 + 入队 parse_upload_tasks（指纹/LLM 清洗）

后台任务：
  upload_worker()        — 消费上传队列：线程池转码/hash + PCM 查重 + 写 UploadStaging
  parse_upload_worker()  — 消费 parse_upload_tasks DB 表，运行 LLM 清洗（持久化，重启恢复）
  fingerprint_worker()   — 空闲时批量计算 Chromaprint + 定期清理过期记录
"""

import base64
import json
import re
import os
import hashlib
import asyncio
import logging
import secrets
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from deps import get_db
from database import SessionLocal
from config import settings
from services.upload_hooks import run_post_fingerprint_hooks
from services.artist_names import (
    add_track_featured_artists,
    artist_names_from_tag_dict,
    dedupe_artist_names,
)
from app_logging import logger as _app_log
import models

router = APIRouter(prefix="/tracks", tags=["Upload"])

RESOURCE_DIR = Path(__file__).parent.parent.parent / "data" / "resource"
COVER_DIR = Path(__file__).parent.parent.parent / "data" / "covers"
SUPPORTED_EXTS = {".flac", ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".ape", ".wma"}

# Lossless formats → transcode to FLAC on ingest
# WMA is conditional (only if codec is wmalossless, checked at runtime)
LOSSLESS_EXTS = frozenset({".ape", ".flac", ".wav", ".wma"})

ART_COLORS = [
    "art-1", "art-2", "art-3", "art-4", "art-5", "art-6",
    "art-7", "art-8", "art-9", "art-10", "art-11", "art-12",
]

_SEP = r"[—–\-]"
_PATTERN = re.compile(r"^(\d+)\.(.*?)" + _SEP + r"(.+)$")

# 专用线程池：无论配置值多大，仍至少为播放/数据库保留 1 个 CPU 核
_cpu_count = os.cpu_count() or 1
_upload_worker_limit = max(1, _cpu_count - 1)
_upload_num_workers  = max(1, min(settings.upload_max_workers, _upload_worker_limit))
_executor = ThreadPoolExecutor(max_workers=_upload_num_workers)

# ── 上传任务队列 ──────────────────────────────────────────────

@dataclass
class _UploadJob:
    """单次上传任务的状态载体，存活于内存中直到被 TTL 清理。"""
    job_id:        str
    save_path:     Path
    original_name: str
    created_at:    float = field(default_factory=_time.time)
    state:         str   = "pending"   # pending | processing | done | error
    result:        dict | None = None  # done 时: {status, file_key} 或 {status, track_id, title}
    error_detail:  str | None = None   # error 时填写

_jobs: dict[str, _UploadJob] = {}

_upload_queue: asyncio.Queue | None = None

def _get_upload_queue() -> "asyncio.Queue[_UploadJob]":
    global _upload_queue
    if _upload_queue is None:
        _upload_queue = asyncio.Queue()
    return _upload_queue

_JOB_TTL = 3600   # done/error 任务在内存中最多保留 1 小时

def _evict_stale_jobs() -> None:
    """清理超过 TTL 的 done/error 任务，防止内存无限增长。"""
    now = _time.time()
    stale = [jid for jid, j in list(_jobs.items()) if now - j.created_at > _JOB_TTL]
    for jid in stale:
        _jobs.pop(jid, None)
    if stale:
        _app_log.debug("upload_jobs 已清理 %d 条过期记录", len(stale))

# 延迟初始化的 DB 写锁（避免模块导入时无 event loop）
_db_write_lock: asyncio.Lock | None = None

def _get_write_lock() -> asyncio.Lock:
    global _db_write_lock
    if _db_write_lock is None:
        _db_write_lock = asyncio.Lock()
    return _db_write_lock

_UPLOAD_STAGING_TTL = 3600  # 秒：upload_staging 孤立记录保留上限（1 小时）

# ── 上传后台 Worker ───────────────────────────────────────────

async def _process_upload_job(loop: asyncio.AbstractEventLoop, job: _UploadJob) -> None:
    """
    单任务处理逻辑（在 upload_worker 内 await）：
      1. run_in_executor：转码 / PCM hash / 时长（线程池，真正并行）
      2. PCM hash 格式无关查重
      3. 写 UploadStaging（供 /create 读取）
    结果写回 job.result；失败写 job.error_detail。
    """
    job.state = "processing"
    original_suffix = job.save_path.suffix.lower()

    try:
        result = await loop.run_in_executor(
            _executor,
            _process_uploaded_file_sync,
            job.save_path, job.original_name,
        )
    except RuntimeError as exc:
        logger.warning(
            "upload_worker 转码失败: file=%s err=%s", job.original_name, exc,
        )
        job.state = "error"
        job.error_detail = str(exc)
        return
    except Exception as exc:
        logger.exception("upload_worker 处理失败: file=%s", job.original_name)
        job.state = "error"
        job.error_detail = f"文件处理失败: {type(exc).__name__}"
        return

    final_suffix = result.pop("final_suffix", original_suffix)
    file_key      = job.save_path.stem + final_suffix  # 转码后可能由 .ape/.wav → .flac
    audio_hash    = result["audio_hash"]
    if audio_hash is None:
        (RESOURCE_DIR / file_key).unlink(missing_ok=True)
        _app_log.error(
            "上传文件无法入库：audio_hash 计算失败 original_name=%s final_path=%s",
            job.original_name,
            RESOURCE_DIR / file_key,
        )
        job.state = "error"
        job.error_detail = "无法计算音频内容 hash，无法入库"
        return

    db = SessionLocal()
    try:
        dup = db.query(models.Track).filter(models.Track.audio_hash == audio_hash).first()
        if dup:
            (RESOURCE_DIR / file_key).unlink(missing_ok=True)
            job.state  = "done"
            job.result = {"status": "duplicate", "track_id": dup.id, "title": dup.title}
            return

        staging = models.UploadStaging(
            file_key=file_key,
            audio_hash=audio_hash,
            original_name=job.original_name,
            duration_sec=result.get("duration", 0),
        )
        db.merge(staging)
        db.commit()
        job.state  = "done"
        job.result = {"status": "ok", "file_key": file_key}
    except Exception as exc:
        db.rollback()
        logger.exception("upload_worker DB 写入失败: file=%s", job.original_name)
        job.state       = "error"
        job.error_detail = f"数据库写入失败: {type(exc).__name__}"
    finally:
        db.close()


async def upload_worker() -> None:
    """
    消费 _upload_queue 中的上传任务。
    main.py 在 lifespan 启动 _upload_num_workers 个实例，与线程池大小一一对应，
    确保每个 worker 拿到任务后立即能获得一个线程，不产生额外排队。
    """
    loop = asyncio.get_event_loop()
    queue = _get_upload_queue()
    while True:
        job: _UploadJob = await queue.get()
        try:
            await _process_upload_job(loop, job)
        except asyncio.CancelledError:
            job.state       = "error"
            job.error_detail = "服务关闭，任务已取消"
            raise
        except Exception:
            logger.exception("upload_worker 未预期异常 job_id=%s", job.job_id)
            job.state       = "error"
            job.error_detail = "内部错误"
        finally:
            queue.task_done()

# ── 元数据解析 ────────────────────────────────────────────────

def _parse_filename(stem: str):
    m = _PATTERN.match(stem)
    if m:
        return int(m.group(1)), m.group(2).strip(), m.group(3).strip()
    return None


def _clean_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _clean_text(item)
            if text:
                return text
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    text = str(value).strip()
    return text or None


def _parse_track_number(value) -> int:
    if isinstance(value, (list, tuple)) and value:
        first = value[0]
        if isinstance(first, (list, tuple)) and first:
            value = first[0]
        else:
            value = first
    text = _clean_text(value)
    if not text:
        return 0
    try:
        return int(text.split("/", 1)[0])
    except Exception:
        return 0


def _detect_cover_ext(data: bytes, mime: str | None = None) -> str:
    if mime is not None and not isinstance(mime, str):
        try:
            from mutagen.mp4 import MP4Cover

            if mime == MP4Cover.FORMAT_PNG:
                return ".png"
        except Exception:
            pass
        mime = str(mime)
    mime = (mime or "").lower()
    if "png" in mime:
        return ".png"
    if "webp" in mime:
        return ".webp"
    if "gif" in mime:
        return ".gif"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def _safe_tag_get(tags, key):
    if tags is None or not hasattr(tags, "get"):
        return None
    try:
        return tags.get(key)
    except Exception:
        return None


def _extract_embedded_cover(audio) -> tuple[bytes | None, str | None]:
    if audio is None:
        return None, None

    pictures = getattr(audio, "pictures", None) or []
    for pic in pictures:
        data = getattr(pic, "data", None)
        if data:
            return data, getattr(pic, "mime", None)

    tags = getattr(audio, "tags", None)
    if tags is None:
        return None, None

    getall = getattr(tags, "getall", None)
    if callable(getall):
        for frame in tags.getall("APIC"):
            data = getattr(frame, "data", None)
            if data:
                return data, getattr(frame, "mime", None)

    if hasattr(tags, "get"):
        for key in ("covr",):
            covers = _safe_tag_get(tags, key) or []
            for cover in covers:
                data = bytes(cover)
                if data:
                    return data, getattr(cover, "imageformat", None)

        for key in ("METADATA_BLOCK_PICTURE", "metadata_block_picture", "COVERART"):
            values = _safe_tag_get(tags, key) or []
            for raw in values:
                try:
                    from mutagen.flac import Picture

                    pic = Picture(base64.b64decode(raw))
                    if pic.data:
                        return pic.data, pic.mime
                except Exception:
                    continue

    return None, None


def _extract_embedded_lyrics(audio) -> str | None:
    if audio is None:
        return None

    tags = getattr(audio, "tags", None)
    if tags is None:
        return None

    getall = getattr(tags, "getall", None)
    if callable(getall):
        for frame in tags.getall("USLT"):
            text = getattr(frame, "text", None)
            if isinstance(text, list):
                joined = "\n".join(part for part in (str(x).strip() for x in text) if part)
                if joined:
                    return joined
            cleaned = _clean_text(text)
            if cleaned:
                return cleaned

    if hasattr(tags, "get"):
        for key in (
            "lyrics",
            "LYRICS",
            "unsyncedlyrics",
            "UNSYNCEDLYRICS",
            "\xa9lyr",
            "----:com.apple.iTunes:LYRICS",
        ):
            cleaned = _clean_text(_safe_tag_get(tags, key))
            if cleaned:
                return cleaned

    return None


def _merge_tag_parsed(pre: dict | None, post: dict | None) -> dict | None:
    """
    无损转码（APE/WAV/WMA → FLAC）后，ffmpeg 输出的 FLAC 往往只带部分标签。
    以转码前在源文件上解析的结果为主，用转码后解析结果仅填补空缺字段。
    """
    if not pre and not post:
        return None
    if not pre:
        return post
    if not post:
        return pre
    out = dict(pre)
    for key in ("track_number", "title", "artist", "album", "release_date", "album_artist", "lyrics", "artists"):
        if key == "track_number":
            if not out.get("track_number") and post.get("track_number"):
                out["track_number"] = post["track_number"]
        elif key == "artists":
            if not out.get("artists") and post.get("artists"):
                out["artists"] = post["artists"]
        else:
            if not out.get(key) and post.get(key):
                out[key] = post[key]
    if not out.get("cover_data") and post.get("cover_data"):
        out["cover_data"] = post["cover_data"]
        out["cover_ext"] = post.get("cover_ext")
    return out


def _parse_tags(filepath: Path):
    try:
        from mutagen import File as MFile
        audio = None
        easy_audio = None
        try:
            easy_audio = MFile(str(filepath), easy=True)
        except Exception:
            pass
        try:
            audio = MFile(str(filepath))
        except Exception:
            pass
        if easy_audio is None:
            with open(filepath, "rb") as fh:
                easy_audio = MFile(fh, easy=True)
        if audio is None:
            with open(filepath, "rb") as fh:
                audio = MFile(fh)
        if not easy_audio and not audio:
            return None

        title = _clean_text((easy_audio.get("title") or [None])[0]) if easy_audio else None
        album = _clean_text((easy_audio.get("album") or [None])[0]) if easy_audio else None
        date = _clean_text((easy_audio.get("date") or [None])[0]) if easy_audio else None
        albumartist_values: list[str] = []
        if easy_audio and easy_audio.get("albumartist") is not None:
            raw_albumartist = easy_audio.get("albumartist")
            if isinstance(raw_albumartist, (list, tuple)):
                for x in raw_albumartist:
                    c = _clean_text(x)
                    if c:
                        albumartist_values.append(c)
            else:
                c = _clean_text(raw_albumartist)
                if c:
                    albumartist_values.append(c)
        albumartist = albumartist_values[0] if albumartist_values else None
        tn = _parse_track_number((easy_audio.get("tracknumber") or [None])[0]) if easy_audio else 0

        artists_list: list[str] = []
        if easy_audio and easy_audio.get("artist") is not None:
            raw_art = easy_audio.get("artist")
            if isinstance(raw_art, (list, tuple)):
                for x in raw_art:
                    c = _clean_text(x)
                    if c:
                        artists_list.append(c)
            else:
                c = _clean_text(raw_art)
                if c:
                    artists_list.append(c)
        artists_list = dedupe_artist_names(artists_list)
        artist = artists_list[0] if artists_list else None
        raw_text_tags: dict[str, str | list[str]] = {}
        if easy_audio:
            for key in sorted(easy_audio.keys()):
                raw_value = easy_audio.get(key)
                values: list[str] = []
                if isinstance(raw_value, (list, tuple)):
                    for x in raw_value:
                        c = _clean_text(x)
                        if c:
                            values.append(c)
                else:
                    c = _clean_text(raw_value)
                    if c:
                        values.append(c)
                if values:
                    raw_text_tags[str(key)] = values if len(values) > 1 else values[0]

        if title and artist:
            cover_data, cover_mime = _extract_embedded_cover(audio)
            return {
                "track_number": tn,
                "title": title,
                "artist": artist,
                "artists": artists_list,
                "album": album,
                "release_date": str(date)[:10] if date else None,
                "album_artist": albumartist,
                "album_artists": albumartist_values,
                "lyrics": _extract_embedded_lyrics(audio),
                "raw_text_tags": raw_text_tags,
                "cover_data": cover_data,
                "cover_ext": _detect_cover_ext(cover_data, cover_mime) if cover_data else None,
            }
    except Exception:
        pass
    return None


def _persist_cover(cover_data: bytes | None, cover_ext: str | None) -> str | None:
    if not cover_data:
        return None
    COVER_DIR.mkdir(exist_ok=True)
    digest = hashlib.sha256(cover_data).hexdigest()
    filename = f"{digest}{cover_ext or '.jpg'}"
    cover_path = COVER_DIR / filename
    if not cover_path.exists():
        cover_path.write_bytes(cover_data)
    return filename


def _apply_cover(tag_parsed: dict | None, album_obj: models.Album | None, track: models.Track) -> None:
    if not tag_parsed:
        return
    filename = _persist_cover(tag_parsed.get("cover_data"), tag_parsed.get("cover_ext"))
    if not filename:
        return
    if album_obj and not album_obj.cover_path:
        album_obj.cover_path = filename
        return
    if not track.cover_path:
        track.cover_path = filename


def _get_duration(filepath: Path) -> int:
    suffix = filepath.suffix.lower()
    if suffix == ".wav":
        try:
            import wave
            with wave.open(str(filepath), "r") as wf:
                frames, rate = wf.getnframes(), wf.getframerate()
                if rate > 0:
                    return int(frames / rate)
        except Exception:
            pass
    try:
        from mutagen import File as MFile
        audio = None
        try:
            audio = MFile(str(filepath))
        except Exception:
            pass
        if audio is None:
            with open(filepath, "rb") as fh:
                audio = MFile(fh)
        if audio and hasattr(audio, "info") and audio.info:
            secs = audio.info.length
            if secs and secs > 0:
                return int(secs)
    except Exception:
        pass
    if suffix == ".flac":
        try:
            from mutagen.flac import FLAC
            with open(filepath, "rb") as fh:
                secs = FLAC(fh).info.length
            if secs > 0:
                return int(secs)
        except Exception:
            pass
    elif suffix == ".mp3":
        try:
            from mutagen.mp3 import MP3
            with open(filepath, "rb") as fh:
                secs = MP3(fh).info.length
            if secs > 0:
                return int(secs)
        except Exception:
            pass
    elif suffix in (".m4a", ".aac"):
        try:
            from mutagen.mp4 import MP4
            with open(filepath, "rb") as fh:
                secs = MP4(fh).info.length
            if secs > 0:
                return int(secs)
        except Exception:
            pass
    try:
        from tinytag import TinyTag
        tag = TinyTag.get(str(filepath))
        if tag.duration and tag.duration > 0:
            return int(tag.duration)
    except Exception:
        pass
    try:
        import soundfile as sf
        info = sf.info(str(filepath))
        if info.duration > 0:
            return int(info.duration)
    except Exception:
        pass
    return 0


def _compute_fingerprint(filepath: Path) -> bytes | None:
    try:
        import subprocess
        # 勿使用 -raw：raw 为未压缩格式，AcoustID lookup 要求默认输出的压缩指纹（见 fpcalc -h）
        result = subprocess.run(
            ["fpcalc", str(filepath)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("FINGERPRINT="):
                    return line.split("=", 1)[1].strip().encode()
            _app_log.warning(
                "fpcalc 成功但未解析到 FINGERPRINT 行: path=%s stdout=%s",
                filepath,
                (result.stdout or "")[:500],
            )
            return None
        err = ((result.stderr or "") + (result.stdout or "")).strip()
        _app_log.warning(
            "fpcalc 指纹失败: path=%s exit=%s %s",
            filepath,
            result.returncode,
            err[:800] + ("..." if len(err) > 800 else "") if err else "无输出",
        )
    except FileNotFoundError:
        _app_log.warning(
            "未找到 fpcalc（Chromaprint），无法计算音频指纹: path=%s。"
            "安装示例：Debian/Ubuntu `apt install libchromaprint-tools`，macOS `brew install chromaprint`。"
            "若不需要指纹可设 FINGERPRINT_ENABLED=false。",
            filepath,
        )
    except Exception as exc:
        _app_log.warning("fpcalc 指纹异常: path=%s err=%s", filepath, exc)
    return None


def _read_flac_md5(filepath: Path) -> bytes | None:
    """
    Read the PCM MD5 stored in the FLAC STREAMINFO block.
    O(1) — no audio decoding required; the encoder wrote this during transcoding.
    Returns None if the signature is all-zero (encoder skipped it) or on error.
    """
    try:
        from mutagen.flac import FLAC
        md5 = bytes(FLAC(str(filepath)).info.md5_signature)
        return md5 if md5 != b"\x00" * 16 else None
    except Exception:
        return None


def _compute_pcm_md5(filepath: Path) -> bytes | None:
    """
    MD5 of decoded PCM float32 — format-agnostic dedup for non-FLAC files.
    Used only for lossy formats (mp3, m4a, aac, ogg) that are stored as-is.
    """
    try:
        import soundfile as sf
        data, _ = sf.read(str(filepath), always_2d=True)
        return hashlib.md5(data.astype("float32").tobytes()).digest()
    except Exception as soundfile_exc:
        pass
    try:
        from pydub import AudioSegment
        seg = AudioSegment.from_file(str(filepath))
        raw = seg.set_channels(2).set_sample_width(4).raw_data
        return hashlib.md5(raw).digest()
    except Exception as pydub_exc:
        _app_log.error(
            "无法计算 audio_hash: path=%s soundfile_error=%s: %s pydub_error=%s: %s",
            filepath,
            type(soundfile_exc).__name__,
            soundfile_exc,
            type(pydub_exc).__name__,
            pydub_exc,
            exc_info=True,
        )
        return None


def _compute_audio_hash(filepath: Path) -> bytes | None:
    """
    Unified format-agnostic audio hash (MD5 of raw PCM):
    - FLAC  → read MD5 directly from STREAMINFO  (free, written by encoder)
    - other → decode PCM and compute MD5          (lossy formats only)
    Since all lossless inputs are converted to FLAC before this is called,
    the fast path is taken for every lossless file.
    """
    if filepath.suffix.lower() == ".flac":
        md5 = _read_flac_md5(filepath)
        if md5:
            return md5
    md5 = _compute_pcm_md5(filepath)
    if md5 is not None and len(md5) != 16:
        _app_log.error("audio_hash 长度异常: path=%s length=%s", filepath, len(md5))
        return None
    return md5


# ── 无损转码 ─────────────────────────────────────────────────

def _is_wma_lossless(path: Path) -> bool:
    """Return True only if the WMA file uses the lossless codec."""
    import subprocess
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10, check=True,
        )
        return r.stdout.strip() == "wmalossless"
    except FileNotFoundError:
        logger.warning("未找到 ffprobe，无法判断 WMA 是否无损，将按非无损处理: %s", path)
        return False
    except subprocess.CalledProcessError as e:
        err = ((e.stderr or "") + (e.stdout or "")).strip() or "无输出"
        logger.warning(
            "ffprobe 探测 WMA 失败: path=%s exit=%s %s",
            path,
            e.returncode,
            err[:800] + ("..." if len(err) > 800 else ""),
        )
        return False
    except Exception as exc:
        logger.warning("ffprobe 探测 WMA 异常: path=%s err=%s", path, exc)
        return False


class _NoBinaryError(RuntimeError):
    """Raised when neither `flac` nor `ffmpeg` is found in PATH."""


def _ffmpeg_failure_message(returncode: int, stderr: bytes) -> str:
    text = (stderr or b"").decode("utf-8", "replace").strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    tail = "；".join(lines[-4:]) if lines else "无详细输出"
    return f"无损转码失败（ffmpeg 退出码 {returncode}）：{tail}"


def _subprocess_output_preview(
    stderr: bytes | None,
    stdout: bytes | None = None,
    *,
    max_chars: int = 800,
) -> str:
    """供日志使用的 stderr/stdout 截断片段。"""
    parts = []
    if stderr:
        t = stderr.decode("utf-8", "replace").strip()
        if t:
            parts.append(t if len(t) <= max_chars else t[: max_chars - 3] + "...")
    if stdout:
        t = stdout.decode("utf-8", "replace").strip()
        if t:
            label = "stdout" if stderr else "out"
            s = t if len(t) <= max_chars else t[: max_chars - 3] + "..."
            parts.append(f"{label}: {s}")
    return " | ".join(parts) if parts else "无详细输出"


def _convert_to_flac(src: Path, dst: Path) -> None:
    """
    Transcode lossless audio to FLAC compression-level 5.

    Strategy:
    - WAV / FLAC: try the native `flac` binary first (supports --verify for
      round-trip encode-decode integrity check; MD5 written to STREAMINFO).
    - APE / WMA / fallback: ffmpeg (ffmpeg's FLAC encoder always embeds MD5
      in STREAMINFO by default).  APE 等容器里内嵌封面常被识别为第二路 mjpeg
      流，故使用 -map 0:a:0 只转音频，避免坏图块导致整段转码失败。

    Raises _NoBinaryError if neither tool is available.
    """
    import subprocess

    suffix = src.suffix.lower()
    if suffix in (".wav", ".flac"):
        try:
            subprocess.run(
                ["flac", "--compression-level-5", "--verify", "--silent",
                 str(src), "-o", str(dst)],
                check=True, capture_output=True, timeout=300,
            )
            return
        except FileNotFoundError:
            # 常见：未安装 flac，回退 ffmpeg；避免每条上传都打 warning
            logger.debug("flac 不在 PATH，回退 ffmpeg: src=%s", src)
        except subprocess.CalledProcessError as e:
            dst.unlink(missing_ok=True)
            logger.warning(
                "flac 编码失败，将回退 ffmpeg: src=%s dst=%s exit=%s %s",
                src,
                dst,
                e.returncode,
                _subprocess_output_preview(e.stderr, e.stdout),
            )

    # ffmpeg path (APE, WMA lossless, and flac-binary fallback)
    try:
        r = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-y", "-i", str(src),
                "-map", "0:a:0",
                "-c:a", "flac", "-compression_level", "5", str(dst),
            ],
            capture_output=True, timeout=300,
        )
    except FileNotFoundError:
        logger.warning(
            "未找到 ffmpeg（或 flac），无法进行无损转码: src=%s",
            src,
        )
        raise _NoBinaryError(
            "neither 'flac' nor 'ffmpeg' found in PATH — "
            "install ffmpeg to enable lossless transcoding"
        )
    if r.returncode != 0:
        dst.unlink(missing_ok=True)
        logger.warning(
            "ffmpeg 转码失败: src=%s exit=%s %s",
            src,
            r.returncode,
            _subprocess_output_preview(r.stderr, r.stdout),
        )
        raise RuntimeError(_ffmpeg_failure_message(r.returncode, r.stderr))


def _flac_channel_count(path: Path) -> int | None:
    """STREAMINFO 声道数；失败时返回 None（由调用方决定是否跳过 ReplayGain）。"""
    try:
        from mutagen.flac import FLAC

        return int(FLAC(str(path)).info.channels)
    except Exception:
        return None


def _add_replaygain(flac_path: Path) -> None:
    """
    Analyse and embed ReplayGain track/album gain + peak tags via metaflac.
    Silently skipped if metaflac is not installed (no WARNING — optional dependency).
    metaflac 仅支持单声道/立体声；多声道（如 5.1）跳过并打 debug。
    """
    ch = _flac_channel_count(flac_path)
    if ch is not None and ch > 2:
        logger.debug(
            "跳过 ReplayGain（metaflac 仅支持 1/2 声道）: path=%s channels=%s",
            flac_path.name,
            ch,
        )
        return

    import subprocess
    try:
        subprocess.run(
            ["metaflac", "--add-replay-gain", str(flac_path)],
            check=True, capture_output=True, timeout=120,
        )
    except FileNotFoundError:
        logger.debug(
            "未找到 metaflac，跳过 ReplayGain: %s（需要时安装 flac 包，含 metaflac）",
            flac_path,
        )
    except subprocess.CalledProcessError as e:
        logger.warning(
            "metaflac ReplayGain 失败: path=%s exit=%s %s",
            flac_path,
            e.returncode,
            _subprocess_output_preview(e.stderr, e.stdout),
        )
    except Exception as exc:
        logger.warning("metaflac ReplayGain 异常: path=%s err=%s", flac_path, exc)


# ── 写库辅助 ──────────────────────────────────────────────────

def _get_or_create_artist(db: Session, name: str) -> models.Artist:
    artist = db.query(models.Artist).filter(models.Artist.name == name).first()
    if not artist:
        color = ART_COLORS[db.query(models.Artist).count() % len(ART_COLORS)]
        artist = models.Artist(
            name=name, art_color=color,
            bio=f"{name} 的本地收藏", monthly_listeners=0,
        )
        db.add(artist)
        db.flush()
    return artist


def _get_or_create_album(
    db: Session,
    title: str,
    artist: models.Artist,
    release_date: str | None = None,
) -> models.Album:
    album = (
        db.query(models.Album)
        .filter(models.Album.title == title, models.Album.artist_id == artist.id)
        .first()
    )
    if not album:
        color = ART_COLORS[db.query(models.Album).count() % len(ART_COLORS)]
        album = models.Album(
            title=title, artist_id=artist.id, art_color=color,
            release_date=release_date, album_type="album",
        )
        db.add(album)
        db.flush()
    elif release_date and not album.release_date:
        album.release_date = release_date
    return album


# ── 线程池工作函数 ────────────────────────────────────────────

def _process_uploaded_file_sync(
    save_path: Path,
    original_name: str,
) -> dict:
    """
    Run in thread pool (truly parallel across concurrent uploads):
    1. Lossless transcode → FLAC level-5 + ReplayGain（仅 APE/WAV/WMA；上传的 FLAC 不重编码）
    2. PCM hash (format-agnostic dedup)
    3. Duration + tag parsing on the final (possibly converted) file
    Fingerprinting is deferred to the background idle worker.
    """
    suffix     = save_path.suffix.lower()
    final_path = save_path
    # 转码前从源文件解析的标签，避免 ffmpeg 输出的 FLAC 缺字段（APE/WAV/WMA）。
    # 上传的 .flac 不再重编码，直接保留原文件（封面与标签完整）。
    tag_pre: dict | None = None

    if suffix in LOSSLESS_EXTS:
        # WMA requires a codec probe; all other lossless exts are always eligible
        do_convert = (suffix != ".wma") or _is_wma_lossless(save_path)

        # .flac：不重编码、不跑 ReplayGain，避免丢 Picture / 改动文件
        if do_convert and suffix != ".flac":
            # APE / WAV / WMA-lossless: must convert — cannot serve these natively.
            # 在删除源文件前先读完整标签；转码后 FLAC 往往只有部分字段。
            try:
                tag_pre = _parse_tags(save_path)
            except Exception:
                tag_pre = None
            flac_path = save_path.with_suffix(".flac")
            if not flac_path.exists():
                try:
                    _convert_to_flac(save_path, flac_path)
                    _add_replaygain(flac_path)
                except _NoBinaryError as exc:
                    flac_path.unlink(missing_ok=True)
                    raise RuntimeError(str(exc)) from exc
                except Exception:
                    flac_path.unlink(missing_ok=True)
                    raise
            save_path.unlink(missing_ok=True)   # original (APE/WAV/WMA) no longer needed
            final_path = flac_path

    audio_hash = _compute_audio_hash(final_path)
    duration   = _get_duration(final_path)
    tag_parsed = _parse_tags(final_path)
    if tag_pre is not None:
        tag_parsed = _merge_tag_parsed(tag_pre, tag_parsed)
    fn_parsed  = _parse_filename(Path(original_name).stem)

    return {
        "audio_hash":   audio_hash,
        "duration":     duration,
        "tag_parsed":   tag_parsed,
        "fn_parsed":    fn_parsed,
        "final_suffix": final_path.suffix,   # ".flac" when converted, original otherwise
    }


# ── Pydantic 模型 ─────────────────────────────────────────────

class CreateTrackRequest(BaseModel):
    file_key: str
    parse_metadata: bool = Field(
        True,
        description="是否入队执行 parse_upload 元数据清洗；false 时仅使用文件内嵌标签写库",
    )
    # 元数据由服务端从上传缓存（LLM 清洗结果 → 文件标签 → 文件名）自动解析，
    # 客户端无需提交。audio_hash / duration_sec 等均从缓存读取。


# ── 端点 ──────────────────────────────────────────────────────

@router.post("/upload-file")
async def upload_file_endpoint(
    file: UploadFile = File(...),
):
    """
    上传单个音频文件，立即返回 {job_id}。

    流程：
    1. 写文件到磁盘
    2. 创建 _UploadJob 并加入 _upload_queue
    3. 立即返回，转码 / hash / 查重 / 写库由后台 upload_worker 处理

    客户端轮询 GET /tracks/upload-status/{job_id} 获取进度，
    state=done 后再调用 POST /tracks/create 写入曲目。
    """
    original_name = Path(file.filename).name
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_EXTS:
        raise HTTPException(400, "不支持的格式")

    save_path = RESOURCE_DIR / (secrets.token_hex(24) + suffix)
    RESOURCE_DIR.mkdir(exist_ok=True)

    with save_path.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)

    _evict_stale_jobs()
    job = _UploadJob(
        job_id=secrets.token_hex(16),
        save_path=save_path,
        original_name=original_name,
    )
    _jobs[job.job_id] = job
    await _get_upload_queue().put(job)

    return {"job_id": job.job_id}


@router.get("/upload-status/{job_id}")
async def upload_status(job_id: str):
    """
    轮询上传任务状态。

    返回：
      {state: "pending"}
      {state: "processing"}
      {state: "done", status: "ok", file_key: "..."}
      {state: "done", status: "duplicate", track_id: N, title: "..."}
      {state: "error", detail: "..."}
    """
    _evict_stale_jobs()
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "任务不存在或已过期")
    if job.state in ("pending", "processing"):
        return {"state": job.state}
    if job.state == "done":
        _jobs.pop(job_id, None)
        return {"state": "done", **(job.result or {})}
    _jobs.pop(job_id, None)
    return {"state": "error", "detail": job.error_detail or "未知错误"}


def enqueue_parse_upload_task(
    db: Session, track_id: int, filename_stem: str, raw_tags: dict | None
) -> None:
    """
    在 DB 写锁内（与 create_track 同一事务）写入 parse_upload_tasks 表。
    parse_upload_worker 轮询该表并运行 LLM 清洗；服务重启后任务自动恢复。
    bytes 字段（cover_data 等）无法 JSON 序列化，写入前过滤。
    """
    safe_tags = (
        {k: v for k, v in raw_tags.items() if not isinstance(v, (bytes, bytearray))}
        if raw_tags else {}
    )
    db.merge(models.ParseUploadTask(
        track_id=track_id,
        filename_stem=filename_stem,
        raw_tags=json.dumps(safe_tags, ensure_ascii=False) if safe_tags else None,
    ))


async def parse_upload_worker() -> None:
    """
    轮询 parse_upload_tasks 表，每次处理一条任务，运行 LLM 标签清洗。
    max_concurrent=1 与 pipeline 信号量一致（Ollama 顺序处理，无意义并发）。
    服务重启后，表中残留的未完成任务自动被拾取。
    """
    while True:
        await asyncio.sleep(3)
        if settings.banana_testing:
            continue
        try:
            await _parse_upload_batch()
        except asyncio.CancelledError:
            raise
        except Exception:
            _app_log.warning("parse_upload_worker 批次异常", exc_info=True)


async def _parse_upload_batch() -> None:
    """取队首任务，运行清洗，成功或无结果均删除任务；异常时保留供下次重试。"""
    db = SessionLocal()
    task: models.ParseUploadTask | None = None
    try:
        task = (
            db.query(models.ParseUploadTask)
            .order_by(models.ParseUploadTask.id)
            .first()
        )
        if task is None:
            return

        track_id      = task.track_id
        filename_stem = task.filename_stem
        raw_tags      = json.loads(task.raw_tags) if task.raw_tags else None

        from services.upload_metadata_enrich import try_enrich_track_from_parse_upload
        await try_enrich_track_from_parse_upload(db, track_id, filename_stem, raw_tags)
        db.commit()

        # 清洗完成（有结果或 LLM 无结果均属正常终态）→ 删除任务
        db.delete(task)
        db.commit()
        task = None   # 标记已删，finally 不再重复删

    except asyncio.CancelledError:
        raise
    except Exception:
        _app_log.warning(
            "_parse_upload_batch 清洗失败 track_id=%s，任务保留待重试",
            task.track_id if task else "?",
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


@router.post("/create")
async def create_track(req: CreateTrackRequest, db: Session = Depends(get_db)):
    """
    根据 file_key 在数据库中创建曲目记录，立即返回 track_id。

    流程：
    1. 从 upload_staging 表读取 audio_hash / 时长 / 原始文件名
    2. 对落盘文件重跑 Mutagen 解析标签（快，< 50 ms）
    3. asyncio.Lock 串行化 DB 写入（SQLite 单写者 / 竞态安全）
    4. 同一事务写入：
       - fingerprint_tasks（Chromaprint 计算队列）
       - parse_upload_tasks（LLM 清洗队列，持久化，重启后自动恢复）
    """
    # ── 前置检查 ──────────────────────────────────────────────
    staging = db.get(models.UploadStaging, req.file_key)
    if staging is None:
        raise HTTPException(404, "上传记录不存在或已过期，请重新上传")

    save_path = RESOURCE_DIR / req.file_key
    if not save_path.exists():
        raise HTTPException(404, "文件不存在，请重新上传")

    # ── 读取暂存数据 ───────────────────────────────────────────
    audio_hash_bytes: bytes = staging.audio_hash
    if audio_hash_bytes is None:
        raise HTTPException(500, "上传记录缺少 audio_hash，请重新上传")
    duration:         int          = staging.duration_sec or 0
    original_name:    str          = staging.original_name
    filename_stem:    str          = Path(original_name).stem

    # ── 快速重解析 Mutagen 标签 ────────────────────────────────
    loop = asyncio.get_event_loop()
    tag: dict | None = await loop.run_in_executor(_executor, _parse_tags, save_path)
    tag = tag or {}

    # 无内嵌标题时不杜撰：不用文件名顶替（界面用 track id 占位）
    title        = _clean_text(tag.get("title")) or ""
    artists      = artist_names_from_tag_dict(tag)
    artist       = tag.get("artist", "")
    album        = tag.get("album")
    track_number = tag.get("track_number") or None  # 0 → None（编号不明）
    release_date = tag.get("release_date")
    album_artist = tag.get("album_artist")
    lyrics       = tag.get("lyrics")

    if not artists and artist:
        artists = [artist]
    if not artists:
        artists = [artist] if artist else ["未知艺人"]
    names = dedupe_artist_names(artists) or ["未知艺人"]

    # ── 串行写库 ──────────────────────────────────────────────
    async with _get_write_lock():
        # 二次查重（并发上传同文件时的安全兜底）
        dup = db.query(models.Track).filter(models.Track.audio_hash == audio_hash_bytes).first()
        if dup:
            db.delete(staging)
            db.commit()
            return {"status": "duplicate", "track_id": dup.id, "title": dup.title}

        album_owner_name = album_artist or names[0]
        primary   = _get_or_create_artist(db, names[0])
        album_obj = None
        if album:
            album_owner = _get_or_create_artist(db, album_owner_name)
            album_obj   = _get_or_create_album(db, album, album_owner, release_date)

        if isinstance(lyrics, str):
            lyrics = lyrics.strip() or None

        track = models.Track(
            title=title,
            album_id=album_obj.id if album_obj else None,
            artist_id=primary.id,
            duration_sec=duration,
            track_number=track_number,
            lyrics=lyrics,
            stream_url=f"/resource/{req.file_key}",
            audio_hash=audio_hash_bytes,
            audio_fingerprint=None,   # 由后台指纹任务填充
        )
        _apply_cover(tag, album_obj, track)
        db.add(track)
        db.delete(staging)   # 消费暂存记录
        try:
            db.flush()
            add_track_featured_artists(db, track.id, names, _get_or_create_artist)
            enqueue_fingerprint_task(db, track.id)
            if req.parse_metadata:
                enqueue_parse_upload_task(db, track.id, filename_stem, tag or None)
            db.commit()
            db.refresh(track)
        except Exception:
            db.rollback()
            raise HTTPException(500, "写库失败")

        track_id = track.id

    return {
        "status":   "added",
        "track_id": track_id,
        "title":    track.title,
        "artist":   names[0],
        "artists":  names,
    }


def enqueue_fingerprint_task(db: Session, track_id: int) -> None:
    """将本地上传曲目加入 Chromaprint 指纹队列；同一 track_id 仅保留一条待处理任务。"""
    if not settings.fingerprint_enabled:
        _app_log.debug("指纹已禁用 (FINGERPRINT_ENABLED)，跳过入队 track_id=%s", track_id)
        return
    if db.query(models.FingerprintTask).filter(models.FingerprintTask.track_id == track_id).first():
        return
    db.add(models.FingerprintTask(track_id=track_id))
    _app_log.info("指纹任务已入队 track_id=%s", track_id)


# ── 后台指纹任务 ──────────────────────────────────────────────

def _evict_stale_upload_staging() -> None:
    """删除 upload_staging 中超过 TTL 的孤立记录，同时清理内存中的过期 job。"""
    _evict_stale_jobs()
    from database import SessionLocal
    cutoff = int(_time.time()) - _UPLOAD_STAGING_TTL
    db = SessionLocal()
    try:
        deleted = (
            db.query(models.UploadStaging)
            .filter(models.UploadStaging.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        if deleted:
            db.commit()
            _app_log.debug("upload_staging 已清理 %d 条过期记录", deleted)
    except Exception:
        db.rollback()
    finally:
        db.close()


_next_staging_cleanup: float = 0.0   # 下次清理 upload_staging 的时间戳


async def fingerprint_worker():
    """
    空闲时消费 fingerprint_tasks 表中的任务并计算 Chromaprint 指纹。
    - 每 1 秒轮询一次；有任务则处理，无任务则跳过
    - 每批最多 3 条任务
    - 任务仅在上传入库（及插件入库）时写入，不扫描 tracks 表
    同时每 5 分钟清理一次超时的 upload_staging 孤立记录。
    """
    global _next_staging_cleanup
    while True:
        await asyncio.sleep(1)
        now = _time.monotonic()
        if now >= _next_staging_cleanup:
            _next_staging_cleanup = now + 300   # 每 5 分钟清理一次
            _evict_stale_upload_staging()
        try:
            await _fingerprint_batch()
        except Exception:
            _app_log.warning("fingerprint_worker 批次异常", exc_info=True)


async def _fingerprint_batch():
    if not settings.fingerprint_enabled:
        return
    db = SessionLocal()
    try:
        tasks = (
            db.query(models.FingerprintTask)
            .order_by(models.FingerprintTask.id)
            .limit(3)
            .all()
        )
        if not tasks:
            return

        loop = asyncio.get_event_loop()

        for task in tasks:
            track = (
                db.query(models.Track)
                .filter(models.Track.id == task.track_id)
                .first()
            )
            if not track:
                db.delete(task)
                continue
            su = (track.stream_url or "").strip()
            if not su.startswith("/resource/"):
                db.delete(task)
                continue
            path = RESOURCE_DIR / Path(su).name
            if not path.exists():
                _app_log.warning(
                    "指纹跳过：音频文件不存在 track_id=%s path=%s",
                    track.id,
                    path,
                )
                db.delete(task)
                continue
            _app_log.info(
                "指纹任务处理中 track_id=%s file=%s",
                track.id,
                path.name,
            )
            fp = await loop.run_in_executor(_executor, _compute_fingerprint, path)
            if fp:
                track.audio_fingerprint = fp
                _app_log.info("指纹写入成功 track_id=%s", track.id)
                await run_post_fingerprint_hooks(db, track)
            else:
                _app_log.warning(
                    "指纹未生成 track_id=%s（请确认已安装 fpcalc，见上方 Chromaprint 日志）",
                    track.id,
                )
            db.delete(task)

        db.commit()
    finally:
        db.close()
