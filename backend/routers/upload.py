"""
routers/upload.py

三步上传 API：
  POST /tracks/upload-file            — 存文件 → 入队 → 立即返回 {job_id}
  GET  /tracks/upload-status/{job_id} — 轮询任务状态（pending/processing/done/error）
  POST /tracks/create                 — asyncio.Lock 串行写库 + 入队指纹任务

后台任务：
  upload_worker()        — 消费上传队列：线程池转码/hash + PCM 查重 + 写 UploadStaging
  fingerprint_worker()   — 空闲时批量计算 Chromaprint + 定期清理过期记录
"""

import re
import os
import hashlib
import asyncio
import logging
import secrets
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

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

# ── 客户端元数据归一化 / 封面持久化 ───────────────────────────


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


def _json_object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key, item in value.items():
        text_key = _clean_text(key)
        if text_key:
            out[text_key] = item
    return out


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


def _compute_soundfile_pcm_md5(filepath: Path) -> bytes | None:
    try:
        import soundfile as sf
        data, _ = sf.read(str(filepath), always_2d=True)
        return hashlib.md5(data.astype("float32").tobytes()).digest()
    except Exception as exc:
        _app_log.error(
            "无法用 soundfile 解码计算 audio_hash: path=%s error=%s: %s",
            filepath,
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return None


def _compute_audio_hash(filepath: Path) -> bytes | None:
    """
    Unified format-agnostic audio hash (MD5 of raw PCM):
    - FLAC  → read STREAMINFO MD5 and verify it by decoding PCM
    - other → decode PCM and compute MD5
    Since all lossless inputs are converted to FLAC before this is called,
    FLAC STREAMINFO mismatch means the file is corrupt or was produced with
    incompatible PCM hash semantics, so ingestion is rejected.
    """
    if filepath.suffix.lower() == ".flac":
        md5 = _compute_soundfile_pcm_md5(filepath)
        streaminfo_md5 = _read_flac_md5(filepath)
        if streaminfo_md5 and md5 and streaminfo_md5 != md5:
            _app_log.error(
                "FLAC STREAMINFO MD5 与实际 PCM MD5 不一致: path=%s streaminfo=%s decoded=%s",
                filepath,
                streaminfo_md5.hex(),
                md5.hex(),
            )
            return None
        if streaminfo_md5 and md5 is None:
            _app_log.error("FLAC 无法解码验证 STREAMINFO MD5: path=%s streaminfo=%s", filepath, streaminfo_md5.hex())
            return None
        if streaminfo_md5:
            return streaminfo_md5
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
    3. Duration on the final (possibly converted) file
    Fingerprinting is deferred to the background idle worker.
    """
    suffix     = save_path.suffix.lower()
    final_path = save_path

    if suffix in LOSSLESS_EXTS:
        # WMA requires a codec probe; all other lossless exts are always eligible
        do_convert = (suffix != ".wma") or _is_wma_lossless(save_path)

        # .flac：不重编码、不跑 ReplayGain，避免丢 Picture / 改动文件
        if do_convert and suffix != ".flac":
            # APE / WAV / WMA-lossless: must convert — cannot serve these natively.
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

    return {
        "audio_hash":   audio_hash,
        "duration":     duration,
        "final_suffix": final_path.suffix,   # ".flac" when converted, original otherwise
    }


# ── Pydantic 模型 ─────────────────────────────────────────────

class CreateTrackMetadata(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    artists: list[str] = Field(default_factory=list)
    album: Optional[str] = None
    album_artist: Optional[str] = None
    album_artists: list[str] = Field(default_factory=list)
    release_date: Optional[str] = None
    track_number: Optional[int] = None
    lyrics: Optional[str] = None
    ext: dict[str, Any] = Field(default_factory=dict)


class CreateTrackRequest(BaseModel):
    file_key: str
    metadata: Optional[CreateTrackMetadata] = Field(
        None,
        description="客户端解析/清洗后的元数据；后端不再解析音频标签",
    )
    cover_id: Optional[str] = Field(None, description="通过 /tracks/covers/upload 上传得到的封面 ID")
    # audio_hash / duration_sec 等均从上传缓存读取，客户端不可提交。


def _metadata_to_tag_dict(metadata: CreateTrackMetadata | None) -> dict:
    if metadata is None:
        return {}
    out: dict = {}
    data = metadata.model_dump(exclude_none=True)

    def cleaned(value) -> str | None:
        return _clean_text(value)

    for key in ("title", "album", "album_artist", "release_date", "lyrics"):
        value = cleaned(data.get(key))
        if value:
            out[key] = value

    artists = [
        text
        for text in (cleaned(x) for x in data.get("artists", []))
        if text
    ]
    if not artists and cleaned(data.get("artist")):
        artists = [cleaned(data.get("artist"))]
    artists = dedupe_artist_names(artists)
    if artists:
        out["artists"] = artists
        out["artist"] = artists[0]

    album_artists = [
        text
        for text in (cleaned(x) for x in data.get("album_artists", []))
        if text
    ]
    if not album_artists and cleaned(data.get("album_artist")):
        album_artists = [cleaned(data.get("album_artist"))]
    album_artists = dedupe_artist_names(album_artists)
    if album_artists:
        out["album_artists"] = album_artists
        out["album_artist"] = album_artists[0]

    track_number = data.get("track_number")
    if track_number is not None:
        try:
            parsed_track_number = int(track_number)
        except (TypeError, ValueError):
            parsed_track_number = 0
        if parsed_track_number > 0:
            out["track_number"] = parsed_track_number

    return out


def _cover_path_from_id(cover_id: str | None) -> str | None:
    if not cover_id:
        return None
    value = cover_id.strip()
    if not re.fullmatch(r"[0-9a-f]{64}\.(?:jpg|jpeg|png|webp|gif)", value):
        raise HTTPException(400, "cover_id 无效")
    if not (COVER_DIR / value).exists():
        raise HTTPException(404, "封面不存在或已过期")
    return value


# ── 端点 ──────────────────────────────────────────────────────

@router.get("/exists-by-hash")
async def exists_by_hash(
    audio_hash: str = Query(..., description="32 位十六进制 audio_hash"),
):
    """
    轻量按 audio_hash 查重。

    匿名可用，供 bulk_import.py 在调用 Ollama 前跳过已存在内容。
    """
    value = audio_hash.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", value):
        raise HTTPException(400, "audio_hash 必须是 32 位十六进制字符串")

    db = SessionLocal()
    try:
        track = db.query(models.Track).filter(models.Track.audio_hash == bytes.fromhex(value)).first()
        if not track:
            return {"exists": False, "track_id": None, "title": None}
        return {"exists": True, "track_id": track.id, "title": track.title}
    finally:
        db.close()


@router.post("/covers/upload")
async def upload_cover_endpoint(file: UploadFile = File(...)):
    """
    上传前端从音频文件中解析出的封面图片，返回 create 可引用的 cover_id。
    后端只验证并持久化图片，不解析音频文件。
    """
    content_type = (file.content_type or "").lower()
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "封面文件过大")
    if not data:
        raise HTTPException(400, "封面文件为空")

    ext = _detect_cover_ext(data, content_type)
    if ext not in {".jpg", ".png", ".webp", ".gif"}:
        raise HTTPException(400, "不支持的封面格式")
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(400, "封面必须是图片")

    cover_id = _persist_cover(data, ext)
    if not cover_id:
        raise HTTPException(500, "封面保存失败")
    return {"cover_id": cover_id, "cover_url": f"/covers/{cover_id}"}


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


@router.post("/create")
async def create_track(req: CreateTrackRequest):
    db = SessionLocal()
    try:
        return await _create_track_in_db(req, db)
    finally:
        db.close()


async def _create_track_in_db(req: CreateTrackRequest, db: Session):
    """
    根据 file_key 在数据库中创建曲目记录，立即返回 track_id。

    流程：
    1. 从 upload_staging 表读取 audio_hash / 时长 / 原始文件名
    2. 使用客户端提交的 metadata 写入初始曲目信息
    3. asyncio.Lock 串行化 DB 写入（SQLite 单写者 / 竞态安全）
    4. 同一事务写入 fingerprint_tasks（Chromaprint 计算队列）
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
    tag = _metadata_to_tag_dict(req.metadata)
    cover_path = _cover_path_from_id(req.cover_id)
    ext = _json_object(req.metadata.ext if req.metadata else {})

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
            is_local=True,
            audio_hash=audio_hash_bytes,
            audio_fingerprint=None,   # 由后台指纹任务填充
            ext=ext,
        )
        if cover_path:
            if album_obj and not album_obj.cover_path:
                album_obj.cover_path = cover_path
            else:
                track.cover_path = cover_path
        db.add(track)
        db.delete(staging)   # 消费暂存记录
        try:
            db.flush()
            add_track_featured_artists(db, track.id, names, _get_or_create_artist)
            enqueue_fingerprint_task(db, track.id)
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

        loop = asyncio.get_running_loop()

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
