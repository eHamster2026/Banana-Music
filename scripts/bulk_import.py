"""
Banana Music batch import helper.

Single entry point for batch import preprocessing workflows.

Subcommands:
  convert  Convert lossless audio to FLAC while preserving tags.
  clean    Use Ollama to parse/clean metadata and print JSON.
  process  Convert when needed, clean metadata, and write tags to a copy.
  upload   Upload audio files to a running Banana Music backend.

Examples:
  python scripts/bulk_import.py convert *.ape --output-dir ./flac/ --level 8
  python scripts/bulk_import.py clean *.mp3 --output results.json
  python scripts/bulk_import.py process *.ape *.mp3 --output-dir ./processed/ --upload
  python scripts/bulk_import.py process *.ape *.mp3 --upload --api-key am_xxx
  python scripts/bulk_import.py process *.ape *.mp3 --upload --no-parse-metadata
  python scripts/bulk_import.py process *.ape *.mp3 --upload --username alice --password secret
  python scripts/bulk_import.py upload ./processed/*.flac --api-key am_xxx
  python scripts/bulk_import.py upload ./processed/*.flac --username alice --password secret

Python deps:
  pip install -r scripts/requirements-bulk-import.txt

System deps:
  ffmpeg, flac
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional


LOSSLESS_EXTS = frozenset({".ape", ".flac", ".wav", ".wma"})
SUPPORTED_EXTS = frozenset({".flac", ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".ape", ".wma"})


def _log_unhandled_exception(context: str, exc: BaseException) -> None:
    logging.error("%s: %s", context, exc, exc_info=True)
    cause = exc.__cause__ or exc.__context__
    if cause:
        chain = []
        visited = set()
        cur = cause
        while cur and id(cur) not in visited:
            visited.add(id(cur))
            chain.append(f"{type(cur).__name__}: {cur}")
            cur = cur.__cause__ or cur.__context__
        logging.error("  原因链: %s", " -> ".join(chain))


def _is_same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a.absolute() == b.absolute()


def _output_path_for(src: Path, output_dir: Path, suffix: str) -> Path:
    dst = output_dir / f"{src.stem}{suffix}"
    if _is_same_path(dst, src):
        dst = output_dir / f"{src.stem}.processed{suffix}"
    return dst


def _expand_paths(patterns: list[str], supported_exts: frozenset[str] | None = None) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        p = Path(pattern)
        if p.exists():
            paths.append(p)
        else:
            expanded = sorted(Path(".").glob(pattern))
            if expanded:
                paths.extend(expanded)
            else:
                logging.warning("找不到文件: %s", pattern)

    if supported_exts is not None:
        unsupported = [p for p in paths if p.suffix.lower() not in supported_exts]
        for p in unsupported:
            logging.warning("不支持的格式，跳过: %s", p.name)
        paths = [p for p in paths if p.suffix.lower() in supported_exts]

    if not paths:
        logging.error("没有有效的文件")
        sys.exit(1)
    return paths


def _first_easy(easy, key: str) -> Optional[str]:
    if easy is None:
        return None
    val = easy.get(key)
    return str(val[0]).strip() or None if val else None


def _easy_values(easy, key: str) -> list[str]:
    if easy is None:
        return []
    val = easy.get(key)
    if not val:
        return []
    return [str(x).strip() for x in val if str(x).strip()]


def _metadata_json_safe(value):
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return None
    if isinstance(value, (list, tuple)):
        cleaned = [_metadata_json_safe(x) for x in value]
        return [x for x in cleaned if x not in (None, "", [], {})]
    if isinstance(value, dict):
        cleaned = {str(k): _metadata_json_safe(v) for k, v in value.items()}
        return {k: v for k, v in cleaned.items() if v not in (None, "", [], {})}
    text = str(value).strip()
    return text or None


def _metadata_for_json(raw_tags: dict) -> dict:
    out: dict = {}
    for key, value in raw_tags.items():
        safe = _metadata_json_safe(value)
        if safe not in (None, "", [], {}):
            out[key] = safe
    return out


def _extract_cover(audio) -> tuple[Optional[bytes], Optional[str]]:
    if hasattr(audio, "pictures") and audio.pictures:
        pic = audio.pictures[0]
        ext = ".png" if getattr(pic, "mime", "").endswith("png") else ".jpg"
        return pic.data, ext

    for key in (audio.keys() if audio else []):
        if key.startswith("APIC"):
            frame = audio[key]
            ext = ".png" if getattr(frame, "mime", "").endswith("png") else ".jpg"
            return frame.data, ext

    covr = audio.get("covr") if audio else None
    if covr:
        from mutagen.mp4 import MP4Cover
        item = covr[0]
        ext = ".png" if getattr(item, "imageformat", None) == MP4Cover.FORMAT_PNG else ".jpg"
        return bytes(item), ext

    for key in ("Cover Art (Front)", "COVER ART (FRONT)"):
        val = audio.get(key) if audio else None
        if val:
            data = bytes(val[0]) if hasattr(val[0], "__bytes__") else val[0].value
            if b"\x00" in data:
                data = data.split(b"\x00", 1)[1]
            ext = ".png" if data[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
            return data, ext

    return None, None


def _parse_full_tags(path: Path) -> dict:
    try:
        import mutagen
        easy = mutagen.File(str(path), easy=True)
        full = mutagen.File(str(path))
    except ImportError:
        logging.error("请安装 mutagen: pip install mutagen")
        return {}
    except Exception as exc:
        logging.warning("标签解析失败 %s: %s", path.name, exc)
        return {}

    if easy is None and full is None:
        return {}

    def _int_first(key: str) -> int:
        raw = _first_easy(easy, key)
        if not raw:
            return 0
        try:
            return int(raw.split("/")[0])
        except ValueError:
            return 0

    artist_values = _easy_values(easy, "artist")
    album_artist_values = _easy_values(easy, "albumartist")
    raw_text_tags: dict = {}
    if easy is not None:
        for key in sorted(easy.keys()):
            values = _easy_values(easy, key)
            if values:
                raw_text_tags[key] = values if len(values) > 1 else values[0]

    result: dict = {
        "title": _first_easy(easy, "title"),
        "artist": artist_values[0] if artist_values else None,
        "artists": artist_values,
        "album": _first_easy(easy, "album"),
        "album_artist": album_artist_values[0] if album_artist_values else None,
        "album_artists": album_artist_values,
        "release_date": (_first_easy(easy, "date") or "")[:10] or None,
        "track_number": _int_first("tracknumber"),
        "lyrics": None,
        "cover_data": None,
        "cover_ext": None,
        "raw_text_tags": raw_text_tags,
    }

    if full:
        for key in ("lyrics", "LYRICS", "unsyncedlyrics", "UNSYNCEDLYRICS", "\xa9lyr", "----:com.apple.iTunes:LYRICS"):
            try:
                val = full.get(key)
            except (ValueError, KeyError):
                continue
            if val:
                text = str(val[0]).strip() if isinstance(val, list) else str(val).strip()
                if text:
                    result["lyrics"] = text
                    break

        cover_data, cover_ext = _extract_cover(full)
        result["cover_data"] = cover_data
        result["cover_ext"] = cover_ext

    return result


def _parse_easy_tags(path: Path) -> dict:
    try:
        import mutagen
        audio = mutagen.File(path, easy=True)
    except ImportError:
        logging.error("请安装 mutagen: pip install mutagen")
        return {}
    except Exception as exc:
        logging.warning("标签解析失败 %s: %s", path.name, exc)
        return {}

    if audio is None:
        return {}

    raw: dict = {
        "title": _first_easy(audio, "title"),
        "artist": _first_easy(audio, "artist"),
        "album": _first_easy(audio, "album"),
        "release_date": _first_easy(audio, "date"),
        "track_number": 0,
    }
    tn_raw = _first_easy(audio, "tracknumber")
    if tn_raw:
        try:
            raw["track_number"] = int(tn_raw.split("/")[0])
        except ValueError:
            pass
    return raw


def _merge_tags(pre: dict, post: dict) -> dict:
    out = dict(pre)
    for key in ("track_number", "title", "artist", "album", "release_date", "album_artist", "lyrics"):
        if key == "track_number":
            if not out.get("track_number") and post.get("track_number"):
                out["track_number"] = post["track_number"]
        elif not out.get(key) and post.get(key):
            out[key] = post[key]
    if not out.get("cover_data") and post.get("cover_data"):
        out["cover_data"] = post["cover_data"]
        out["cover_ext"] = post.get("cover_ext")
    return out


def _detect_flac_level(path: Path) -> int:
    try:
        from mutagen.flac import FLAC
        audio = FLAC(str(path))
        tag = audio.get("compression_level")
        if tag:
            try:
                return int(tag[0])
            except (ValueError, IndexError):
                pass
        return 2 if audio.info.max_blocksize <= 1152 else 5
    except Exception:
        return 5


def _write_tags_to_flac(path: Path, tags: dict, *, level: Optional[int] = None) -> bool:
    try:
        from mutagen.flac import FLAC, Picture
        from mutagen.id3 import PictureType
    except ImportError:
        logging.error("请安装 mutagen: pip install mutagen")
        return False

    try:
        audio = FLAC(str(path))
    except Exception as exc:
        logging.warning("打开 FLAC 失败 %s: %s", path.name, exc)
        return False

    mapping = {
        "title": "title",
        "artist": "artist",
        "album": "album",
        "album_artist": "albumartist",
        "release_date": "date",
    }

    def _tag_values(value) -> list[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            return [str(x).strip() for x in value if str(x).strip()]
        text = str(value).strip()
        return [text] if text else []

    for src_key, vorbis_key in mapping.items():
        values = _tag_values(tags.get(src_key))
        if values:
            audio[vorbis_key] = values

    if tags.get("track_number"):
        audio["tracknumber"] = [str(tags["track_number"])]
    if tags.get("lyrics"):
        audio["lyrics"] = [tags["lyrics"]]
    if level is not None:
        audio["compression_level"] = [str(level)]

    cover_data = tags.get("cover_data")
    if cover_data:
        pic = Picture()
        pic.type = PictureType.COVER_FRONT
        ext = tags.get("cover_ext") or ".jpg"
        pic.mime = "image/png" if ext == ".png" else "image/jpeg"
        pic.data = cover_data
        audio.clear_pictures()
        audio.add_picture(pic)

    try:
        audio.save()
        logging.debug("标签写入完成: %s", path.name)
        return True
    except Exception as exc:
        logging.warning("标签写入失败 %s: %s", path.name, exc)
        return False


def _is_wma_lossless(path: Path) -> bool:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "a:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return r.stdout.strip() == "wmalossless"
    except FileNotFoundError:
        logging.warning("未找到 ffprobe，无法判断 WMA 是否无损，按非无损处理: %s", path.name)
        return False
    except Exception as exc:
        logging.warning("ffprobe 探测 WMA 失败 %s: %s", path.name, exc)
        return False


class _NoBinaryError(RuntimeError):
    pass


def _convert_to_flac(src: Path, dst: Path, level: int = 5) -> None:
    suffix = src.suffix.lower()

    if suffix in (".wav", ".flac"):
        try:
            subprocess.run(
                ["flac", f"--compression-level-{level}", "--verify", "--silent", str(src), "-o", str(dst)],
                check=True,
                capture_output=True,
                timeout=300,
            )
            logging.debug("flac binary 转码完成: %s -> %s", src.name, dst.name)
            return
        except FileNotFoundError:
            logging.debug("flac 不在 PATH，回退 ffmpeg: %s", src.name)
        except subprocess.CalledProcessError as exc:
            dst.unlink(missing_ok=True)
            stderr = (exc.stderr or b"").decode("utf-8", "replace").strip()
            logging.warning("flac 编码失败，回退 ffmpeg: %s\n%s", src.name, stderr)

    try:
        r = subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                "-y", "-i", str(src), "-map", "0:a:0",
                "-c:a", "flac", "-compression_level", str(level), str(dst),
            ],
            capture_output=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise _NoBinaryError("未找到 flac 或 ffmpeg，请安装后重试")

    if r.returncode != 0:
        dst.unlink(missing_ok=True)
        stderr = (r.stderr or b"").decode("utf-8", "replace").strip()
        lines = [line.strip() for line in stderr.splitlines() if line.strip()]
        detail = "；".join(lines[-4:]) if lines else "无详细输出"
        raise RuntimeError(f"ffmpeg 转码失败（exit {r.returncode}）：{detail}")

    logging.debug("ffmpeg 转码完成: %s -> %s", src.name, dst.name)


def _add_replaygain(path: Path) -> None:
    try:
        from mutagen.flac import FLAC
        channels = FLAC(str(path)).info.channels
    except Exception:
        channels = None

    if channels is not None and channels > 2:
        logging.debug("跳过 ReplayGain（metaflac 仅支持 <=2 声道）: %s", path.name)
        return

    try:
        subprocess.run(["metaflac", "--add-replay-gain", str(path)], check=True, capture_output=True, timeout=120)
        logging.debug("ReplayGain 已写入: %s", path.name)
    except FileNotFoundError:
        logging.debug("未找到 metaflac，跳过 ReplayGain")
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", "replace").strip()
        logging.warning("metaflac ReplayGain 失败 %s: %s", path.name, stderr)


def convert_file(
    src: Path,
    output_dir: Optional[Path],
    *,
    level: int = 5,
    replaygain: bool,
    tags_only: bool,
    overwrite: bool,
) -> Optional[Path]:
    suffix = src.suffix.lower()

    if output_dir is None:
        logging.error("[%s] 需要显式指定 --output-dir；如需输出到当前目录，请使用 --output-dir .", src.name)
        return None

    if tags_only:
        if suffix != ".flac":
            logging.warning("--tags-only 仅支持 FLAC 文件，跳过: %s", src.name)
            return None
        dst = _output_path_for(src, output_dir, src.suffix)
        if dst.exists() and not overwrite:
            logging.warning("[%s] 目标已存在，跳过（--overwrite 覆盖）: %s", src.name, dst.name)
            return None
        logging.info("[%s] 复制到输出目录并补写副本标签...", src.name)
        shutil.copy2(src, dst)
        tags = _parse_full_tags(dst)
        if tags:
            _write_tags_to_flac(dst, tags)
            logging.info("[%s] 完成 -> %s", src.name, dst)
        else:
            logging.warning("[%s] 无可读标签，跳过", src.name)
        return dst

    if suffix not in LOSSLESS_EXTS:
        logging.warning("不支持的格式，跳过: %s（支持: %s）", src.name, ", ".join(sorted(LOSSLESS_EXTS)))
        return None

    if suffix == ".wma" and not _is_wma_lossless(src):
        logging.info("[%s] WMA 有损编码，跳过", src.name)
        return None

    dst = _output_path_for(src, output_dir, ".flac")

    if suffix == ".flac":
        detected = _detect_flac_level(src)
        if detected >= level:
            logging.info("[%s] FLAC level %d >= 目标 %d，跳过重编码", src.name, detected, level)
            if dst != src:
                if dst.exists() and not overwrite:
                    logging.warning("[%s] 目标已存在，跳过（--overwrite 覆盖）", src.name)
                    return None
                shutil.copy2(src, dst)
            tags = _parse_full_tags(dst)
            if tags:
                _write_tags_to_flac(dst, tags, level=detected)
            return dst
        logging.info("[%s] FLAC level %d < 目标 %d，重编码提升压缩率...", src.name, detected, level)

    if dst.exists() and not overwrite:
        logging.warning("[%s] 目标已存在，跳过（使用 --overwrite 覆盖）: %s", src.name, dst.name)
        return None

    logging.info("[%s] 读取源文件标签...", src.name)
    tag_pre = _parse_full_tags(src)

    logging.info("[%s] 转码为 FLAC...", src.name)
    try:
        _convert_to_flac(src, dst, level=level)
    except _NoBinaryError as exc:
        logging.error("%s", exc)
        return None
    except RuntimeError as exc:
        logging.error("[%s] 转码失败: %s", src.name, exc)
        return None

    if replaygain:
        logging.info("[%s] 写入 ReplayGain...", src.name)
        _add_replaygain(dst)

    logging.info("[%s] 读取转码后标签...", src.name)
    tag_post = _parse_full_tags(dst)
    merged = _merge_tags(tag_pre, tag_post) if tag_pre else tag_post
    if merged:
        logging.info("[%s] 写入输出文件合并标签...", src.name)
        _write_tags_to_flac(dst, merged, level=level)
    else:
        logging.warning("[%s] 无可用标签，跳过写入", src.name)

    logging.info("[%s] 完成 -> %s", src.name, dst)
    return dst


@dataclass
class MetadataResult:
    title: Optional[str] = None
    artists: list = field(default_factory=list)
    album: Optional[str] = None
    track_number: Optional[int] = None
    confidence: float = 0.0


_SYSTEM_PROMPT = """\
You are a music metadata parser. Given a filename and optional raw tags, extract and clean the music metadata.

Rules:
1. Return ONLY valid JSON — no explanation, no markdown.
2. Split multiple artists on: feat. / ft. / & / 、/ ; — each becomes a separate list element.
3. The first element of "artists" is the primary artist.
4. If title and artist appear swapped (e.g. artist looks like a song name), correct them.
5. Strip track numbers, dashes, underscores, brackets from title when they are clearly noise.
6. Remove source/site/watermark/uploader/release-group tokens from all metadata fields,
   including title, artists, and album. If such a token is attached to valid metadata,
   keep the valid music metadata and remove only the source token.
   Examples: "[51ape.com]陶喆" -> "陶喆"; "【example.net】Some Artist" -> "Some Artist".
7. Set a field to null if it genuinely cannot be determined.
8. "track_number" must be an integer (0 if unknown).

Output schema (strict):
{
  "title": "<song title>",
  "artists": ["<primary artist>", "<featured artist>", ...],
  "album": "<album name or null>",
  "track_number": 0
}"""

_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _build_user_message(filename_stem: str, raw_tags: dict) -> str:
    lines = [f'filename: "{filename_stem}"']
    relevant = _metadata_for_json({
        key: raw_tags[key]
        for key in (
            "title",
            "artist",
            "artists",
            "album",
            "album_artist",
            "album_artists",
            "track_number",
            "release_date",
            "lyrics",
            "raw_text_tags",
        )
        if raw_tags.get(key)
    })
    if relevant:
        lines.append(f"tags: {json.dumps(relevant, ensure_ascii=False)}")
    return "\n".join(lines)


def _parse_llm_response(content: str) -> Optional[dict]:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    match = _JSON_RE.search(content)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _hint_ollama_model_missing(model: str, http_body: str) -> str:
    try:
        data = json.loads(http_body)
    except json.JSONDecodeError:
        return ""
    err = str(data.get("error", "")).lower()
    if "not found" not in err or "model" not in err:
        return ""
    return (
        f" 未安装模型 {model!r}：在运行 Ollama 的主机执行 `ollama pull {model}`。"
        f"标签须与官方库一致（勿写成 qwen35；Qwen3.5 见 https://ollama.com/library/qwen3.5 ）。"
    )


def _text_from_native_chat(body: dict) -> Optional[str]:
    msg = body.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if content is not None and str(content).strip():
            return str(content)
    return None


def _text_from_openai_compat(body: dict) -> Optional[str]:
    choices = body.get("choices")
    if not choices or not isinstance(choices, list):
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    msg = first.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if content is not None and str(content).strip():
            return str(content)
    return None


def _text_from_generate(body: dict) -> Optional[str]:
    content = body.get("response")
    if content is not None and str(content).strip():
        return str(content)
    return None


async def _ollama_infer_json(
    client,
    base_url: str,
    model: str,
    user_msg: str,
    *,
    think: bool = False,
) -> str:
    """Return model text content (expected JSON). Tries chat, OpenAI compat, then generate."""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    chat_payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "think": think,
        "options": {"temperature": 0},
    }
    last_err: Optional[str] = None

    r = await client.post(f"{base_url}/api/chat", json=chat_payload)
    if 200 <= r.status_code < 300:
        try:
            text = _text_from_native_chat(r.json())
            if text is not None:
                return text
        except json.JSONDecodeError:
            pass
    else:
        last_err = f"/api/chat HTTP {r.status_code}"

    openai_base = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "stream": False,
    }
    r = await client.post(
        f"{base_url}/v1/chat/completions",
        json={**openai_base, "response_format": {"type": "json_object"}},
    )
    if r.status_code == 400:
        r = await client.post(f"{base_url}/v1/chat/completions", json=openai_base)
    if 200 <= r.status_code < 300:
        try:
            text = _text_from_openai_compat(r.json())
            if text is not None:
                return text
        except json.JSONDecodeError:
            pass
    else:
        last_err = f"/v1/chat/completions HTTP {r.status_code}"

    gen_payload = {
        "model": model,
        "system": _SYSTEM_PROMPT,
        "prompt": user_msg,
        "format": "json",
        "stream": False,
        "think": think,
        "options": {"temperature": 0},
    }
    r = await client.post(f"{base_url}/api/generate", json=gen_payload)
    try:
        r.raise_for_status()
    except Exception as exc:
        tail = (r.text or "")[:400]
        missing = _hint_ollama_model_missing(model, r.text or "")
        openai_note = ""
        if last_err and "v1/chat/completions" in last_err and "404" in last_err:
            openai_note = "（/v1/chat/completions 404 时升级 Ollama 可启用 OpenAI 兼容层，见 https://docs.ollama.com/openai ）"
        raise RuntimeError(
            f"Ollama 推理均失败（{last_err or 'chat/openai 无有效正文'}；"
            f"最后 /api/generate HTTP {r.status_code} {tail!r}）{missing}{openai_note}"
        ) from exc
    try:
        body = r.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ollama /api/generate 返回非 JSON: {(r.text or '')[:200]!r}") from exc
    text = _text_from_generate(body)
    if text is None:
        raise RuntimeError(f"Ollama /api/generate 响应无 response 文本: {body!r}")
    return text


def _coerce_result(data: dict) -> Optional[MetadataResult]:
    title = data.get("title")
    if isinstance(title, str):
        title = title.strip() or None

    raw_artists = data.get("artists") or []
    if isinstance(raw_artists, str):
        raw_artists = [raw_artists]
    artists = [artist.strip() for artist in raw_artists if isinstance(artist, str) and artist.strip()]

    album = data.get("album")
    if isinstance(album, str):
        album = album.strip() or None

    try:
        track_number = int(data.get("track_number") or 0) or None
    except (TypeError, ValueError):
        track_number = None

    if not title and not artists:
        return None
    return MetadataResult(title=title, artists=artists, album=album, track_number=track_number, confidence=0.9)


async def _llm_clean(
    filename_stem: str,
    raw_tags: dict,
    ollama_url: str,
    model: str,
    timeout: float,
) -> Optional[MetadataResult]:
    try:
        import httpx
    except ImportError:
        logging.error("请安装 httpx: pip install httpx")
        return None

    user_msg = _build_user_message(filename_stem, raw_tags)

    async with httpx.AsyncClient(timeout=timeout) as client:
        content = await _ollama_infer_json(
            client,
            ollama_url,
            model,
            user_msg,
            think=False,
        )

    if not content:
        logging.warning("[%s] Ollama 无有效响应", filename_stem)
        return None

    data = _parse_llm_response(content)
    if data is None:
        logging.warning("[%s] 无法从 LLM 输出解析 JSON: %r", filename_stem, content[:200])
        return None
    return _coerce_result(data)


async def clean_file(path: Path, ollama_url: str, model: str, timeout: float) -> dict:
    raw_tags = _parse_full_tags(path)
    output: dict = {"file": str(path), "raw_tags": _metadata_for_json(raw_tags)}

    logging.info("[%s] 调用 Ollama (%s)...", path.stem, model)
    try:
        result = await _llm_clean(path.stem, raw_tags, ollama_url, model, timeout)
    except Exception as exc:
        _log_unhandled_exception(f"[{path.stem}] LLM 失败", exc)
        result = None

    if result:
        output["result"] = asdict(result)
        logging.info("[%s] 结果: title=%r artists=%r album=%r", path.stem, result.title, result.artists, result.album)
    else:
        output["result"] = None
        logging.info("[%s] 无结果", path.stem)
    return output


def _write_cleaned_tags(path: Path, llm: MetadataResult) -> bool:
    suffix = path.suffix.lower()

    if suffix == ".flac":
        tags: dict = {
            "title": llm.title,
            "artist": llm.artists or None,
            "album": llm.album,
            "track_number": llm.track_number,
        }
        return _write_tags_to_flac(path, tags)

    if suffix == ".ogg":
        try:
            from mutagen.oggvorbis import OggVorbis
            audio = OggVorbis(str(path))
        except Exception as exc:
            logging.warning("OGG 标签写入失败 %s: %s", path.name, exc)
            return False
    elif suffix == ".mp3":
        try:
            from mutagen.easyid3 import EasyID3
            try:
                audio = EasyID3(str(path))
            except Exception:
                import mutagen.id3
                mutagen.id3.ID3().save(str(path))
                audio = EasyID3(str(path))
        except Exception as exc:
            logging.warning("MP3 标签写入失败 %s: %s", path.name, exc)
            return False
    elif suffix in (".m4a", ".aac"):
        try:
            from mutagen.easymp4 import EasyMP4
            audio = EasyMP4(str(path))
        except Exception as exc:
            logging.warning("M4A 标签写入失败 %s: %s", path.name, exc)
            return False
    else:
        logging.debug("不支持写入标签的格式，跳过: %s", path.suffix)
        return False

    if llm.title:
        audio["title"] = [llm.title]
    if llm.artists:
        audio["artist"] = [str(x).strip() for x in llm.artists if str(x).strip()]
    if llm.album:
        audio["album"] = [llm.album]
    if llm.track_number:
        audio["tracknumber"] = [str(llm.track_number)]

    try:
        audio.save()
        logging.debug("LLM 标签写入完成: %s", path.name)
        return True
    except Exception as exc:
        logging.warning("标签保存失败 %s: %s", path.name, exc)
        return False


async def process_file(
    src: Path,
    output_dir: Optional[Path],
    *,
    level: int,
    replaygain: bool,
    overwrite: bool,
    skip_convert: bool,
    skip_llm: bool,
    ollama_url: str,
    ollama_model: str,
    ollama_timeout: float,
) -> dict:
    if output_dir is None:
        return {"file": str(src), "converted": None, "final_file": str(src), "llm_result": None, "error": "需要输出目录"}

    suffix = src.suffix.lower()
    result: dict = {"file": str(src), "converted": None, "final_file": str(src), "llm_result": None}
    final_path = src

    if not skip_convert and suffix in LOSSLESS_EXTS:
        if suffix == ".flac":
            logging.info("[%s] 已是 FLAC，跳过转码", src.name)
        else:
            logging.info("[%s] 无损格式，转码为 FLAC...", src.name)
            converted = convert_file(
                src,
                output_dir,
                level=level,
                replaygain=replaygain,
                tags_only=False,
                overwrite=overwrite,
            )
            if converted is None:
                logging.warning("[%s] 转码失败，终止", src.name)
                result["error"] = "转码失败"
                return result
            final_path = converted
            result["converted"] = str(converted)
            result["final_file"] = str(final_path)
            logging.info("[%s] 转码完成 -> %s", src.name, converted.name)

    if output_dir and final_path == src:
        dst = _output_path_for(src, output_dir, src.suffix)
        if dst != src:
            if dst.exists() and not overwrite:
                logging.warning("[%s] 目标已存在，终止（--overwrite 覆盖）: %s", src.name, dst)
                result["error"] = "目标已存在"
                return result
            shutil.copy2(src, dst)
            final_path = dst
            result["converted"] = str(dst)
            result["final_file"] = str(final_path)
            logging.info("[%s] 已复制 -> %s", src.name, dst.name)

    if not skip_llm:
        raw_tags = _parse_full_tags(final_path)
        logging.info("[%s] 调用 Ollama (%s)...", final_path.stem, ollama_model)
        try:
            llm = await _llm_clean(final_path.stem, raw_tags, ollama_url, ollama_model, ollama_timeout)
        except Exception as exc:
            _log_unhandled_exception(f"[{final_path.stem}] LLM 失败", exc)
            llm = None

        if llm:
            result["llm_result"] = asdict(llm)
            logging.info("[%s] LLM 结果: title=%r artists=%r", final_path.stem, llm.title, llm.artists)
            logging.info("[%s] 写入副本标签...", final_path.stem)
            if not _write_cleaned_tags(final_path, llm):
                result["error"] = "LLM清洗结果写入失败"
        else:
            logging.warning("[%s] LLM 无有效解析结果，跳过后续上传", final_path.stem)
            result["error"] = "LLM解析失败"

    return result


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _auth_headers(api_key: Optional[str], token: Optional[str]) -> dict[str, str]:
    if token:
        return {"Authorization": f"Bearer {token}"}
    if api_key:
        return {"x-api-key": api_key}
    return {}


async def upload_file_to_backend(
    path: Path,
    *,
    base_url: str,
    api_key: Optional[str],
    token: Optional[str],
    parse_metadata: bool,
    poll_interval: float,
    job_timeout: float,
    request_timeout: float,
) -> dict:
    try:
        import httpx
    except ImportError:
        logging.error("请安装 httpx: pip install httpx")
        return {"file": str(path), "status": "error", "detail": "missing httpx"}

    base_url = base_url.rstrip("/")
    headers = _auth_headers(api_key, token)
    file_hash = _sha256_file(path)

    async with httpx.AsyncClient(timeout=request_timeout, headers=headers) as client:
        logging.info("[%s] 预检重复...", path.name)
        r = await client.get(f"{base_url}/tracks/check-hash", params={"h": file_hash})
        r.raise_for_status()
        check = r.json()
        if check.get("exists"):
            track_id = check.get("track_id")
            logging.info("[%s] 已存在，track_id=%s", path.name, track_id)
            return {"file": str(path), "status": "duplicate", "track_id": track_id, "title": check.get("title")}

        logging.info("[%s] 上传文件...", path.name)
        with path.open("rb") as f:
            r = await client.post(
                f"{base_url}/tracks/upload-file",
                data={"file_hash": file_hash},
                files={"file": (path.name, f, "application/octet-stream")},
            )
        r.raise_for_status()
        job_id = r.json()["job_id"]

        deadline = asyncio.get_running_loop().time() + job_timeout
        while True:
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"上传任务超时: {job_id}")
            await asyncio.sleep(poll_interval)
            s = await client.get(f"{base_url}/tracks/upload-status/{job_id}")
            s.raise_for_status()
            state = s.json()
            if state.get("state") in ("pending", "processing"):
                continue
            if state.get("state") == "error":
                detail = state.get("detail") or "未知错误"
                raise RuntimeError(f"上传任务失败: {detail}")
            if state.get("state") != "done":
                raise RuntimeError(f"未知上传状态: {state}")

            if state.get("status") == "duplicate":
                track_id = state.get("track_id")
                logging.info("[%s] 内容重复，track_id=%s", path.name, track_id)
                return {"file": str(path), "status": "duplicate", "track_id": track_id, "title": state.get("title")}

            file_key = state.get("file_key")
            if not file_key:
                raise RuntimeError(f"上传完成但缺少 file_key: {state}")

            logging.info("[%s] 写入曲库...", path.name)
            created = await client.post(
                f"{base_url}/tracks/create",
                json={"file_key": file_key, "parse_metadata": parse_metadata},
            )
            created.raise_for_status()
            data = created.json()
            logging.info("[%s] 完成，status=%s track_id=%s", path.name, data.get("status"), data.get("track_id"))
            return {"file": str(path), **data}


async def login_to_backend(
    *,
    base_url: str,
    username: str,
    password: str,
    request_timeout: float,
) -> str:
    try:
        import httpx
    except ImportError:
        raise RuntimeError("请安装 httpx: pip install httpx")

    base_url = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=request_timeout) as client:
        r = await client.post(
            f"{base_url}/auth/login",
            json={"username": username, "password": password},
        )
        r.raise_for_status()
        body = r.json()
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"登录成功但响应缺少 access_token: {body}")
    return str(token)


async def resolve_upload_token(args: argparse.Namespace) -> Optional[str]:
    if args.token:
        return args.token
    if args.username or args.password:
        if not args.username or not args.password:
            raise RuntimeError("--username 与 --password 必须同时提供")
        logging.info("使用用户名/密码登录: %s", args.username)
        return await login_to_backend(
            base_url=args.base_url,
            username=args.username,
            password=args.password,
            request_timeout=args.request_timeout,
        )
    return None


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")


def _add_convert_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("files", nargs="+", metavar="FILE", help="输入文件路径")
    parser.add_argument("--output-dir", "-d", default=None, type=Path, help="输出目录（必填；如需当前目录请传 .）")
    parser.add_argument("--level", "-l", default=5, type=int, choices=range(0, 13), metavar="0-12", help="FLAC 压缩级别 0-12（默认 5）")
    parser.add_argument("--no-replaygain", dest="replaygain", action="store_false", default=True, help="跳过 ReplayGain 分析")
    parser.add_argument("--tags-only", action="store_true", help="仅在输出副本中补写 FLAC 缺失标签，不重新转码")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的输出文件")


def _add_llm_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ollama-url", default="http://localhost:11434", help="Ollama 服务地址（默认 http://localhost:11434）")
    parser.add_argument("--model", default="qwen3.5:latest", help="Ollama 模型名称（默认 qwen3.5:latest）")
    parser.add_argument("--timeout", default=120.0, type=float, help="LLM 调用超时秒数（默认 120）")


def _add_upload_options(parser: argparse.ArgumentParser, *, include_upload_flag: bool = False) -> None:
    if include_upload_flag:
        parser.add_argument("--upload", action="store_true", help="处理完成后直接上传到 Banana Music 后端")
    parser.add_argument("--base-url", default=os.getenv("BANANA_BASE_URL", "http://localhost:8000"), help="Banana Music 后端地址（默认 http://localhost:8000，或 BANANA_BASE_URL）")
    parser.add_argument("--api-key", default=os.getenv("BANANA_API_KEY"), help="API Key（可用 BANANA_API_KEY）")
    parser.add_argument("--token", default=os.getenv("BANANA_TOKEN"), help="Bearer token（可用 BANANA_TOKEN；优先于 API Key）")
    parser.add_argument("--username", default=os.getenv("BANANA_USERNAME"), help="登录用户名（可用 BANANA_USERNAME；优先级低于 --token，高于 API Key）")
    parser.add_argument("--password", default=os.getenv("BANANA_PASSWORD"), help="登录密码（可用 BANANA_PASSWORD；与 --username 同时使用）")
    parser.add_argument("--no-parse-metadata", dest="parse_metadata", action="store_false", default=True, help="上传写库后不入队服务端 parse_upload 元数据清洗")
    parser.add_argument("--poll-interval", default=0.8, type=float, help="上传任务轮询间隔秒数（默认 0.8）")
    parser.add_argument("--job-timeout", default=120.0, type=float, help="单文件上传后台任务超时秒数（默认 120）")
    parser.add_argument("--request-timeout", default=120.0, type=float, help="HTTP 请求超时秒数（默认 120）")


async def _run_convert(args: argparse.Namespace) -> None:
    if args.output_dir is None:
        logging.error("convert 需要显式指定 --output-dir；如需输出到当前目录，请使用 --output-dir .")
        sys.exit(1)
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    ok, skipped = 0, 0
    for path in _expand_paths(args.files):
        converted = convert_file(
            path,
            args.output_dir,
            level=args.level,
            replaygain=args.replaygain,
            tags_only=args.tags_only,
            overwrite=args.overwrite,
        )
        if converted is None:
            skipped += 1
        else:
            ok += 1
    logging.info("完成：成功 %d  跳过 %d", ok, skipped)


async def _run_clean(args: argparse.Namespace) -> None:
    paths = _expand_paths(args.files, SUPPORTED_EXTS)
    results = [
        await clean_file(path, args.ollama_url.rstrip("/"), args.model, args.timeout)
        for path in paths
    ]
    output_data = results[0] if len(results) == 1 else results
    output_str = json.dumps(output_data, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_str, encoding="utf-8")
        logging.info("结果已写入: %s", args.output)
    else:
        print(output_str)


async def _run_process(args: argparse.Namespace) -> None:
    if args.skip_convert and args.skip_llm:
        logging.error("--skip-convert 和 --skip-llm 不能同时使用")
        sys.exit(1)
    if not args.upload and args.output_dir is None:
        logging.error("process 未使用 --upload 时需要显式指定 --output-dir；如需输出到当前目录，请使用 --output-dir .")
        sys.exit(1)
    results: list[dict] = []

    temp_dir_ctx = None
    effective_output_dir = args.output_dir
    if effective_output_dir:
        effective_output_dir.mkdir(parents=True, exist_ok=True)
    elif args.upload:
        temp_dir_ctx = tempfile.TemporaryDirectory(prefix="banana-bulk-import-")
        effective_output_dir = Path(temp_dir_ctx.name)
        logging.info("未指定 --output-dir，使用临时目录处理上传文件: %s", effective_output_dir)

    try:
        upload_token = await resolve_upload_token(args) if args.upload else args.token
        for path in _expand_paths(args.files, SUPPORTED_EXTS):
            logging.info("─── 处理: %s", path)
            result = await process_file(
                path,
                effective_output_dir,
                level=args.level,
                replaygain=args.replaygain,
                overwrite=args.overwrite,
                skip_convert=args.skip_convert,
                skip_llm=args.skip_llm,
                ollama_url=args.ollama_url.rstrip("/"),
                ollama_model=args.model,
                ollama_timeout=args.timeout,
            )
            if args.upload and not result.get("error"):
                try:
                    result["upload_result"] = await upload_file_to_backend(
                        Path(result["final_file"]),
                        base_url=args.base_url,
                        api_key=args.api_key,
                        token=upload_token,
                        parse_metadata=args.parse_metadata,
                        poll_interval=args.poll_interval,
                        job_timeout=args.job_timeout,
                        request_timeout=args.request_timeout,
                    )
                except Exception as exc:
                    _log_unhandled_exception(f"[{result['final_file']}] 上传失败", exc)
                    result["upload_result"] = {"status": "error", "detail": str(exc)}
            results.append(result)
    finally:
        if temp_dir_ctx is not None:
            temp_dir_ctx.cleanup()
    logging.info("全部完成")


async def _run_upload(args: argparse.Namespace) -> None:
    results: list[dict] = []
    upload_token = await resolve_upload_token(args)
    with tempfile.TemporaryDirectory(prefix="banana-bulk-upload-") as tmp:
        tmp_dir = Path(tmp)
        for path in _expand_paths(args.files, SUPPORTED_EXTS):
            try:
                dst = tmp_dir / path.name
                counter = 1
                while dst.exists():
                    dst = tmp_dir / f"{path.stem}.{counter}{path.suffix}"
                    counter += 1
                shutil.copy2(path, dst)

                raw_tags = _parse_full_tags(dst)
                logging.info("[%s] 上传前调用 Ollama (%s)...", path.stem, args.model)
                try:
                    llm = await _llm_clean(dst.stem, raw_tags, args.ollama_url.rstrip("/"), args.model, args.timeout)
                except Exception as exc:
                    _log_unhandled_exception(f"[{path.stem}] LLM 失败，跳过上传", exc)
                    results.append({"file": str(path), "status": "skipped", "detail": "LLM解析失败"})
                    continue

                if not llm:
                    logging.warning("[%s] LLM 无有效解析结果，跳过上传", path.stem)
                    results.append({"file": str(path), "status": "skipped", "detail": "LLM解析失败"})
                    continue

                logging.info("[%s] LLM 结果: title=%r artists=%r", path.stem, llm.title, llm.artists)
                if not _write_cleaned_tags(dst, llm):
                    logging.warning("[%s] LLM 清洗结果写入失败，跳过上传", path.stem)
                    results.append({"file": str(path), "status": "skipped", "detail": "LLM清洗结果写入失败"})
                    continue

                uploaded = await upload_file_to_backend(
                    dst,
                    base_url=args.base_url,
                    api_key=args.api_key,
                    token=upload_token,
                    parse_metadata=args.parse_metadata,
                    poll_interval=args.poll_interval,
                    job_timeout=args.job_timeout,
                    request_timeout=args.request_timeout,
                )
                results.append({"source_file": str(path), "llm_result": asdict(llm), **uploaded})
            except Exception as exc:
                _log_unhandled_exception(f"[{path}] 上传失败", exc)
                results.append({"file": str(path), "status": "error", "detail": str(exc)})

    ok = sum(1 for r in results if r.get("status") == "added")
    duplicate = sum(1 for r in results if r.get("status") == "duplicate")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    failed = sum(1 for r in results if r.get("status") == "error")
    logging.info("上传完成：新增 %d  重复 %d  跳过 %d  失败 %d", ok, duplicate, skipped, failed)


async def _amain(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Banana Music 批量导入预处理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_convert = subparsers.add_parser("convert", help="无损音频转 FLAC，保留完整元数据")
    _add_convert_options(p_convert)
    _add_common_options(p_convert)
    p_convert.set_defaults(func=_run_convert)

    p_clean = subparsers.add_parser("clean", help="通过 Ollama LLM 清洗元数据并输出 JSON")
    p_clean.add_argument("files", nargs="+", metavar="FILE", help="音乐文件路径")
    p_clean.add_argument("--output", "-o", default=None, help="输出 JSON 文件路径（默认 stdout）")
    _add_llm_options(p_clean)
    _add_common_options(p_clean)
    p_clean.set_defaults(func=_run_clean)

    p_process = subparsers.add_parser("process", help="转码 + LLM 清洗并写入副本标签")
    p_process.add_argument("files", nargs="+", metavar="FILE", help="输入文件路径")
    p_process.add_argument("--output-dir", "-d", default=None, type=Path, help="输出目录；未设置且 --upload 时使用临时目录，未 --upload 时必填")
    p_process.add_argument("--level", "-l", default=5, type=int, choices=range(0, 13), metavar="0-12", help="FLAC 压缩级别 0-12（默认 5）")
    p_process.add_argument("--no-replaygain", dest="replaygain", action="store_false", default=True, help="跳过 ReplayGain 分析")
    p_process.add_argument("--skip-convert", action="store_true", help="跳过格式转换，仅做 LLM 清洗")
    p_process.add_argument("--skip-llm", action="store_true", help="跳过 LLM 清洗，仅做格式转换")
    p_process.add_argument("--overwrite", action="store_true", help="覆盖已存在的输出文件")
    _add_llm_options(p_process)
    _add_upload_options(p_process, include_upload_flag=True)
    _add_common_options(p_process)
    p_process.set_defaults(func=_run_process)

    p_upload = subparsers.add_parser("upload", help="LLM 清洗临时副本后上传到 Banana Music 后端")
    p_upload.add_argument("files", nargs="+", metavar="FILE", help="输入文件路径")
    _add_llm_options(p_upload)
    _add_upload_options(p_upload)
    _add_common_options(p_upload)
    p_upload.set_defaults(func=_run_upload)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(message)s",
        stream=sys.stderr,
    )
    await args.func(args)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
