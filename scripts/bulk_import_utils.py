"""Shared helpers for Banana Music bulk upload scripts."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


LOSSLESS_EXTS = frozenset({".ape", ".flac", ".wav", ".wma"})
SUPPORTED_EXTS = frozenset({".flac", ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".ape", ".wma"})


@dataclass
class MetadataResult:
    title: Optional[str] = None
    artists: list = field(default_factory=list)
    album: Optional[str] = None
    album_artist: Optional[str] = None
    album_artists: list = field(default_factory=list)
    track_number: Optional[int] = None
    confidence: float = 0.0


def _auth_headers(api_key: Optional[str], token: Optional[str]) -> dict[str, str]:
    if token:
        return {"Authorization": f"Bearer {token}"}
    if api_key:
        return {"x-api-key": api_key}
    return {}


def iter_audio_files(root: Path, *, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in root.glob(pattern)
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS
    )


def _tag_values(audio, key: str) -> list[str]:
    if audio is None or not hasattr(audio, "get"):
        return []
    try:
        value = audio.get(key)
    except Exception:
        return []
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _clean_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_track_number(value) -> int | None:
    text = _clean_text(value)
    if not text:
        return None
    try:
        number = int(text.split("/", 1)[0])
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _ffprobe_tag_sets(path: Path, timeout: float) -> list[dict[str, object]] | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format_tags:stream_tags",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        logging.warning("[%s] 标签检查超时 %.1fs，跳过", path.name, timeout)
        return []
    except Exception as exc:
        logging.warning("[%s] ffprobe 标签检查失败，跳过: %s", path.name, exc)
        return []

    if result.returncode != 0:
        logging.warning("[%s] ffprobe 无法读取标签，跳过: %s", path.name, (result.stderr or "").strip())
        return []

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        logging.warning("[%s] ffprobe 标签输出不是 JSON，跳过", path.name)
        return []

    tag_sets: list[dict[str, object]] = []
    format_tags = data.get("format", {}).get("tags")
    if isinstance(format_tags, dict):
        tag_sets.append(format_tags)
    streams = data.get("streams")
    if isinstance(streams, list):
        for stream in streams:
            tags = stream.get("tags") if isinstance(stream, dict) else None
            if isinstance(tags, dict):
                tag_sets.append(tags)
    return tag_sets


def _tag_value_from_sets(tag_sets: list[dict[str, object]], *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    for tags in tag_sets:
        for key, value in tags.items():
            if str(key).casefold() not in wanted:
                continue
            text = _clean_text(value)
            if text:
                return text
    return None


def _has_title_and_artist_via_ffprobe(path: Path, timeout: float) -> bool | None:
    tag_sets = _ffprobe_tag_sets(path, timeout)
    if tag_sets is None:
        return None
    return bool(
        _tag_value_from_sets(tag_sets, "title")
        and _tag_value_from_sets(tag_sets, "artist")
    )


def has_title_and_artist_tags(path: Path, *, timeout: float = 5.0) -> bool:
    ffprobe_result = _has_title_and_artist_via_ffprobe(path, timeout)
    if ffprobe_result is not None:
        return ffprobe_result

    try:
        from mutagen import File as MutagenFile
    except ImportError:
        logging.error("请安装 ffprobe 或 mutagen 后再检查本地标签")
        return False

    try:
        audio = MutagenFile(str(path), easy=True)
    except Exception as exc:
        logging.warning("[%s] 标签读取失败，跳过: %s", path.name, exc)
        return False

    return bool(_tag_values(audio, "title") and _tag_values(audio, "artist"))


def _metadata_via_ffprobe(path: Path, timeout: float) -> MetadataResult | None:
    tag_sets = _ffprobe_tag_sets(path, timeout)
    if tag_sets is None:
        return None
    if not tag_sets:
        return MetadataResult()

    title = _tag_value_from_sets(tag_sets, "title")
    artist = _tag_value_from_sets(tag_sets, "artist")
    album = _tag_value_from_sets(tag_sets, "album")
    album_artist = _tag_value_from_sets(tag_sets, "album_artist", "albumartist", "album artist")
    track_number = _parse_track_number(
        _tag_value_from_sets(tag_sets, "track", "tracknumber", "track_number")
    )

    artists = [artist] if artist else []
    album_artists = [album_artist] if album_artist else []
    return MetadataResult(
        title=title,
        artists=artists,
        album=album,
        album_artist=album_artist,
        album_artists=album_artists,
        track_number=track_number,
        confidence=1.0 if title and artists else 0.0,
    )


def read_embedded_metadata(path: Path, *, timeout: float = 5.0) -> MetadataResult | None:
    """Read embedded tags for upload scripts, preferring ffprobe for speed and format coverage."""
    ffprobe_result = _metadata_via_ffprobe(path, timeout)
    if ffprobe_result is not None and ffprobe_result.title and ffprobe_result.artists:
        return ffprobe_result

    try:
        from mutagen import File as MutagenFile
    except ImportError:
        if ffprobe_result is not None:
            return ffprobe_result
        logging.error("请安装 ffprobe 或 mutagen 后再读取本地标签")
        return None

    try:
        audio = MutagenFile(str(path), easy=True)
    except Exception as exc:
        logging.warning("[%s] 标签读取失败，跳过: %s", path.name, exc)
        return ffprobe_result
    if audio is None:
        return ffprobe_result or MetadataResult()

    artists = _tag_values(audio, "artist")
    album_artists = _tag_values(audio, "albumartist")
    title_values = _tag_values(audio, "title")
    album_values = _tag_values(audio, "album")
    track_values = _tag_values(audio, "tracknumber")
    return MetadataResult(
        title=title_values[0] if title_values else None,
        artists=artists,
        album=album_values[0] if album_values else None,
        album_artist=album_artists[0] if album_artists else None,
        album_artists=album_artists,
        track_number=_parse_track_number(track_values[0] if track_values else None),
        confidence=1.0 if title_values and artists else 0.0,
    )


def add_auth_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default=os.getenv("BANANA_BASE_URL", "http://localhost:8000"), help="Banana Music 后端地址")
    parser.add_argument("--api-key", default=os.getenv("BANANA_API_KEY"), help="API Key（可用 BANANA_API_KEY）")
    parser.add_argument("--token", default=os.getenv("BANANA_TOKEN"), help="Bearer token（可用 BANANA_TOKEN；优先于 API Key）")
    parser.add_argument("--username", default=os.getenv("BANANA_USERNAME"), help="登录用户名（可用 BANANA_USERNAME）")
    parser.add_argument("--password", default=os.getenv("BANANA_PASSWORD"), help="登录密码（可用 BANANA_PASSWORD）")


async def _stage_file_to_backend(
    client,
    path: Path,
    base_url: str,
    poll_interval: float,
    job_timeout: float,
) -> dict:
    logging.info("[%s] 上传文件并查重...", path.name)
    with path.open("rb") as f:
        response = await client.post(
            f"{base_url}/rest/x-banana/tracks/upload-file",
            files={"file": (path.name, f, "application/octet-stream")},
        )
    response.raise_for_status()
    job_id = response.json()["job_id"]

    deadline = asyncio.get_running_loop().time() + job_timeout
    while True:
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError(f"上传任务超时: {job_id}")
        await asyncio.sleep(poll_interval)
        status_response = await client.get(f"{base_url}/rest/x-banana/tracks/upload-status/{job_id}")
        status_response.raise_for_status()
        state = status_response.json()
        if state.get("state") in ("pending", "processing"):
            continue
        if state.get("state") == "error":
            detail = state.get("detail") or "未知错误"
            raise RuntimeError(f"上传任务失败: {detail}")
        if state.get("state") != "done":
            raise RuntimeError(f"未知上传状态: {state}")
        return state


def _metadata_payload(metadata: MetadataResult) -> dict:
    return {
        "title": metadata.title,
        "artists": metadata.artists,
        "album": metadata.album,
        "album_artist": metadata.album_artist,
        "album_artists": metadata.album_artists,
        "track_number": metadata.track_number,
    }


async def upload_file_with_client(
    client,
    path: Path,
    *,
    base_url: str,
    parse_metadata: bool,
    metadata: Optional[MetadataResult] = None,
    poll_interval: float,
    job_timeout: float,
) -> dict:
    base_url = base_url.rstrip("/")
    state = await _stage_file_to_backend(client, path, base_url, poll_interval, job_timeout)
    if state.get("status") == "duplicate":
        track_id = state.get("track_id")
        logging.info("[%s] 内容重复，track_id=%s", path.name, track_id)
        return {"file": str(path), "status": "duplicate", "track_id": track_id, "title": state.get("title")}

    file_key = state.get("file_key")
    if not file_key:
        raise RuntimeError(f"上传完成但缺少 file_key: {state}")

    _ = parse_metadata  # retained for older callers; server-side parse_upload queue was removed
    payload = {"file_key": file_key}
    if metadata is not None:
        payload["metadata"] = _metadata_payload(metadata)

    logging.info("[%s] 写入曲库...", path.name)
    created = await client.post(
        f"{base_url}/rest/x-banana/tracks/create",
        json=payload,
    )
    created.raise_for_status()
    data = created.json()
    logging.info("[%s] 完成，status=%s track_id=%s", path.name, data.get("status"), data.get("track_id"))
    return {"file": str(path), **data}


async def upload_file_to_backend(
    path: Path,
    *,
    base_url: str,
    api_key: Optional[str],
    token: Optional[str],
    parse_metadata: bool,
    metadata: Optional[MetadataResult] = None,
    poll_interval: float,
    job_timeout: float,
    request_timeout: float,
) -> dict:
    try:
        import httpx
    except ImportError:
        logging.error("请安装 httpx: pip install httpx")
        return {"file": str(path), "status": "error", "detail": "missing httpx"}

    headers = _auth_headers(api_key, token)
    async with httpx.AsyncClient(timeout=request_timeout, headers=headers) as client:
        return await upload_file_with_client(
            client,
            path,
            base_url=base_url,
            parse_metadata=parse_metadata,
            metadata=metadata,
            poll_interval=poll_interval,
            job_timeout=job_timeout,
        )


async def login_to_backend(
    *,
    base_url: str,
    username: str,
    password: str,
    request_timeout: float,
) -> str:
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("请安装 httpx: pip install httpx") from exc

    base_url = base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=request_timeout) as client:
        response = await client.post(
            f"{base_url}/rest/x-banana/auth/login",
            json={"username": username, "password": password},
        )
        response.raise_for_status()
        body = response.json()
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
