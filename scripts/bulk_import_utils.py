"""Shared helpers for Banana Music bulk upload scripts."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
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

    payload = {"file_key": file_key, "parse_metadata": parse_metadata}
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
