"""
Upload an audio directory as one album without LLM cleanup.

The current Banana Music backend supports one album cover image (albums.cover_path),
but it does not have album description or multiple album image fields.

Example:
  python scripts/upload_album_dir.py /path/to/album --album-title "Album Name" --api-key am_xxx
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

from bulk_import_utils import (
    EmbeddedCover,
    MetadataResult,
    SUPPORTED_EXTS,
    _auth_headers,
    add_auth_options,
    read_embedded_metadata,
    resolve_upload_token,
    upload_file_to_backend,
)


IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
TEXT_EXTS = frozenset({".txt", ".md", ".markdown"})
COVER_STEMS = ("cover", "front", "folder")
DESCRIPTION_STEMS = ("description", "album", "readme", "README")


def collect_audio_files(directory: Path, *, recursive: bool) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return [
        path
        for path in directory.glob(pattern)
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS
    ]


def album_tracks_with_track_numbers(paths: list[Path], *, metadata_timeout: float) -> list[tuple[Path, int | None]]:
    tracks: list[tuple[Path, int | None]] = []
    for path in paths:
        metadata = read_embedded_metadata(path, timeout=metadata_timeout)
        tracks.append((path, metadata.track_number if metadata else None))
    return tracks


def _norm_title(value: str) -> str:
    return " ".join(value.casefold().split())


def select_cover_image(directory: Path) -> tuple[Optional[Path], list[Path]]:
    images = sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTS)
    if not images:
        return None, []

    by_name = {path.name.casefold(): path for path in images}
    for name in ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp"):
        if name in by_name:
            chosen = by_name[name]
            return chosen, [path for path in images if path != chosen]

    for stem in COVER_STEMS:
        for path in images:
            if path.stem.casefold() == stem:
                return path, [item for item in images if item != path]

    chosen = images[0]
    return chosen, [path for path in images if path != chosen]


def select_description_file(directory: Path) -> Optional[Path]:
    text_files = sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in TEXT_EXTS)
    if not text_files:
        return None

    for stem in DESCRIPTION_STEMS:
        for path in text_files:
            if path.stem == stem or path.stem.casefold() == stem.casefold():
                return path
    return text_files[0]


def detect_cover_ext(data: bytes, fallback: str = ".jpg") -> str:
    suffix = fallback.lower()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    return suffix if suffix in IMAGE_EXTS else ".jpg"


def copy_to_tmp(src: Path, tmp_dir: Path) -> Path:
    dst = tmp_dir / src.name
    counter = 1
    while dst.exists():
        dst = tmp_dir / f"{src.stem}.{counter}{src.suffix}"
        counter += 1
    shutil.copy2(src, dst)
    return dst


async def fetch_existing_albums(base_url: str, headers: dict[str, str], request_timeout: float) -> list[dict]:
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("请安装 httpx: pip install httpx") from exc

    albums: list[dict] = []
    skip = 0
    limit = 500
    async with httpx.AsyncClient(timeout=request_timeout, headers=headers) as client:
        while True:
            resp = await client.get(
                f"{base_url.rstrip('/')}/rest/getAlbumList2",
                params={"skip": skip, "limit": limit},
            )
            resp.raise_for_status()
            page = resp.json()
            if not isinstance(page, list):
                raise RuntimeError(f"getAlbumList2 返回非列表: {page!r}")
            albums.extend(page)
            if len(page) < limit:
                break
            skip += limit
    return albums


async def ensure_album_title_available(
    album_title: str,
    *,
    base_url: str,
    headers: dict[str, str],
    request_timeout: float,
    allow_existing: bool,
) -> None:
    albums = await fetch_existing_albums(base_url, headers, request_timeout)
    conflicts = [item for item in albums if _norm_title(str(item.get("title", ""))) == _norm_title(album_title)]
    if conflicts and not allow_existing:
        ids = ", ".join(str(item.get("id")) for item in conflicts)
        raise RuntimeError(f"专辑名称已存在: {album_title!r} (album_id: {ids})；如需追加请使用 --allow-existing-album")
    if conflicts:
        logging.warning("专辑名称已存在，将继续追加到现有同名专辑: %s", album_title)


def embed_cover(path: Path, cover_data: bytes, cover_ext: str) -> bool:
    suffix = path.suffix.lower()
    mime = "image/png" if cover_ext == ".png" else "image/webp" if cover_ext == ".webp" else "image/jpeg"

    try:
        if suffix == ".flac":
            from mutagen.flac import FLAC, Picture

            audio = FLAC(str(path))
            pic = Picture()
            pic.type = 3
            pic.mime = mime
            pic.data = cover_data
            audio.clear_pictures()
            audio.add_picture(pic)
            audio.save()
            return True

        if suffix == ".mp3":
            from mutagen.id3 import APIC, ID3

            try:
                tags = ID3(str(path))
            except Exception:
                tags = ID3()
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_data))
            tags.save(str(path), v2_version=3)
            return True

        if suffix in (".m4a", ".aac"):
            from mutagen.mp4 import MP4, MP4Cover

            audio = MP4(str(path))
            imageformat = MP4Cover.FORMAT_PNG if cover_ext == ".png" else MP4Cover.FORMAT_JPEG
            audio["covr"] = [MP4Cover(cover_data, imageformat=imageformat)]
            audio.save()
            return True

        if suffix == ".ogg":
            from mutagen.flac import Picture
            from mutagen.oggvorbis import OggVorbis

            audio = OggVorbis(str(path))
            pic = Picture()
            pic.type = 3
            pic.mime = mime
            pic.data = cover_data
            audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
            audio.save()
            return True
    except Exception as exc:
        logging.warning("[%s] 写入专辑封面失败: %s", path.name, exc)
        return False

    logging.warning("[%s] 当前格式不支持写入目录封面: %s", path.name, suffix)
    return False


async def run(args: argparse.Namespace) -> None:
    directory = args.directory.expanduser()
    if not directory.is_dir():
        logging.error("目录不存在: %s", directory)
        sys.exit(1)

    album_title = args.album_title or directory.name
    album_artist = args.album_artist or "Various Artists"
    paths = collect_audio_files(directory, recursive=not args.no_recursive)
    if not paths:
        logging.error("目录下没有支持的音频文件: %s", directory)
        sys.exit(1)
    tracks = album_tracks_with_track_numbers(paths, metadata_timeout=args.metadata_check_timeout)

    token = await resolve_upload_token(args)
    headers = _auth_headers(args.api_key, token)
    await ensure_album_title_available(
        album_title,
        base_url=args.base_url,
        headers=headers,
        request_timeout=args.request_timeout,
        allow_existing=args.allow_existing_album,
    )

    description_file = select_description_file(directory)
    if description_file:
        logging.warning("发现专辑描述文本，但当前服务端没有专辑描述字段，未提交: %s", description_file.name)

    cover_path, extra_images = select_cover_image(directory)
    cover_data = cover_path.read_bytes() if cover_path else None
    cover_ext = detect_cover_ext(cover_data, cover_path.suffix if cover_path else ".jpg") if cover_data else None
    if cover_path:
        logging.info("选择专辑封面: %s", cover_path.name)
    if extra_images:
        logging.warning(
            "发现额外图片但当前服务端只支持单张 album.cover_path，未提交: %s",
            ", ".join(path.name for path in extra_images),
        )

    results: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="banana-album-upload-") as tmp:
        tmp_dir = Path(tmp)
        for index, (source, track_number) in enumerate(tracks, start=1):
            track_label = track_number if track_number is not None else "-"
            logging.info("[%d/%d] 上传专辑曲目: %s track_number=%s", index, len(tracks), source.name, track_label)
            try:
                upload_path = copy_to_tmp(source, tmp_dir)
                cover = EmbeddedCover(data=cover_data, ext=cover_ext) if cover_data and cover_ext else None

                metadata = MetadataResult(
                    album=album_title,
                    album_artist=album_artist,
                    album_artists=[album_artist],
                    track_number=track_number,
                )
                uploaded = await upload_file_to_backend(
                    upload_path,
                    base_url=args.base_url,
                    api_key=args.api_key,
                    token=token,
                    parse_metadata=False,
                    metadata=metadata,
                    cover=cover,
                    poll_interval=args.poll_interval,
                    job_timeout=args.job_timeout,
                    request_timeout=args.request_timeout,
                )
                uploaded["source_file"] = str(source)
                results.append(uploaded)
            except Exception as exc:
                logging.error("[%s] 上传失败: %s", source, exc, exc_info=args.verbose)
                results.append({"file": str(source), "status": "error", "detail": str(exc)})

    added = sum(1 for item in results if item.get("status") == "added")
    duplicate = sum(1 for item in results if item.get("status") == "duplicate")
    failed = sum(1 for item in results if item.get("status") == "error")
    skipped = sum(1 for item in results if item.get("status") == "skipped")
    logging.info(
        "专辑提交完成：album=%r artist=%r 新增 %d  重复 %d  跳过 %d  失败 %d",
        album_title,
        album_artist,
        added,
        duplicate,
        skipped,
        failed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="将目录下音频作为一个专辑提交，不做 LLM 清洗")
    parser.add_argument("directory", type=Path, help="专辑目录")
    parser.add_argument("--album-title", help="专辑名；默认使用目录名")
    parser.add_argument("--album-artist", help="专辑艺人；默认 Various Artists")
    parser.add_argument("--allow-existing-album", action="store_true", help="允许同名专辑已存在时继续追加")
    parser.add_argument("--no-recursive", action="store_true", help="只读取目录第一层")
    parser.add_argument("--metadata-check-timeout", default=5.0, type=float, help="单文件 TRACKNUMBER 标签读取超时秒数")
    parser.add_argument("--poll-interval", default=0.8, type=float, help="上传任务轮询间隔秒数")
    parser.add_argument("--job-timeout", default=120.0, type=float, help="单文件上传后台任务超时秒数")
    parser.add_argument("--request-timeout", default=120.0, type=float, help="HTTP 请求超时秒数")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    add_auth_options(parser)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(message)s",
    )
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
