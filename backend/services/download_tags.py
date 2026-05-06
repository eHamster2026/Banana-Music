from __future__ import annotations

import base64
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import models

logger = logging.getLogger(__name__)


@dataclass
class DownloadImage:
    path: Path
    image_type: str
    mime_type: str


_PIC_TYPES = {
    "cover": 3,
    "front": 3,
    "back": 4,
    "artist": 8,
    "fanart": 0,
}


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _artist_names(track: models.Track) -> list[str]:
    names = []
    if track.artist and track.artist.name:
        names.append(track.artist.name)
    for rel in sorted(track.track_artists or [], key=lambda item: item.sort_order):
        if rel.artist and rel.artist.name and rel.artist.name not in names:
            names.append(rel.artist.name)
    return names


def _album_artist(track: models.Track) -> str | None:
    if track.album and track.album.artist and track.album.artist.name:
        return track.album.artist.name
    return track.artist.name if track.artist else None


def _metadata(track: models.Track) -> dict[str, Any]:
    data: dict[str, Any] = {
        "title": _safe_text(track.title),
        "artist": _artist_names(track),
        "album": _safe_text(track.album.title) if track.album else None,
        "albumartist": _album_artist(track),
        "tracknumber": str(track.track_number) if track.track_number else None,
        "date": _safe_text(track.album.release_date) if track.album else None,
        "lyrics": _safe_text(track.lyrics),
    }
    for key, value in (track.ext or {}).items():
        if key in data or value in (None, "", [], {}):
            continue
        if isinstance(value, (str, int, float, bool)):
            data[key] = str(value)
    return {key: value for key, value in data.items() if value not in (None, "", [], {})}


def _copy_to_temp(source: Path) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        prefix="banana-download-",
        suffix=source.suffix,
        delete=False,
    )
    tmp_path = Path(tmp.name)
    tmp.close()
    shutil.copy2(source, tmp_path)
    return tmp_path


def _image_bytes(image: DownloadImage) -> bytes | None:
    try:
        return image.path.read_bytes()
    except OSError:
        logger.warning("download image missing: %s", image.path)
        return None


def _cover_only(images: list[DownloadImage]) -> list[DownloadImage]:
    return [image for image in images if image.image_type == "cover"][:1]


def _set_easy_tags(audio, metadata: dict[str, Any]) -> None:
    for key, value in metadata.items():
        if key == "artist" and isinstance(value, list):
            audio[key] = value
        else:
            audio[key] = [str(value)] if not isinstance(value, list) else [str(x) for x in value]


def _write_flac(path: Path, metadata: dict[str, Any], images: list[DownloadImage]) -> None:
    from mutagen.flac import FLAC, Picture

    audio = FLAC(str(path))
    _set_easy_tags(audio, metadata)
    audio.clear_pictures()
    for image in images:
        data = _image_bytes(image)
        if not data:
            continue
        pic = Picture()
        pic.type = _PIC_TYPES.get(image.image_type, 0)
        pic.mime = image.mime_type
        pic.desc = image.image_type
        pic.data = data
        audio.add_picture(pic)
    audio.save()


def _write_mp3(path: Path, metadata: dict[str, Any], images: list[DownloadImage]) -> None:
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import APIC, ID3, USLT

    try:
        easy = EasyID3(str(path))
    except Exception:
        easy = EasyID3()
    easy_map = {key: value for key, value in metadata.items() if key != "lyrics"}
    _set_easy_tags(easy, easy_map)
    easy.save(str(path))

    tags = ID3(str(path))
    tags.delall("APIC")
    tags.delall("USLT")
    if metadata.get("lyrics"):
        tags.add(USLT(encoding=3, lang="und", desc="lyrics", text=str(metadata["lyrics"])))
    for image in images:
        data = _image_bytes(image)
        if not data:
            continue
        tags.add(APIC(
            encoding=3,
            mime=image.mime_type,
            type=_PIC_TYPES.get(image.image_type, 0),
            desc=image.image_type,
            data=data,
        ))
    tags.save(str(path))


def _write_mp4(path: Path, metadata: dict[str, Any], images: list[DownloadImage]) -> None:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(str(path))
    key_map = {
        "title": "\xa9nam",
        "album": "\xa9alb",
        "albumartist": "aART",
        "date": "\xa9day",
        "lyrics": "\xa9lyr",
    }
    for key, mp4_key in key_map.items():
        if metadata.get(key):
            audio[mp4_key] = [str(metadata[key])]
    artists = metadata.get("artist")
    if artists:
        audio["\xa9ART"] = [", ".join(artists) if isinstance(artists, list) else str(artists)]
    if metadata.get("tracknumber"):
        try:
            audio["trkn"] = [(int(str(metadata["tracknumber"]).split("/", 1)[0]), 0)]
        except ValueError:
            pass
    covers = []
    for image in _cover_only(images):
        data = _image_bytes(image)
        if not data:
            continue
        fmt = MP4Cover.FORMAT_PNG if image.mime_type == "image/png" else MP4Cover.FORMAT_JPEG
        covers.append(MP4Cover(data, imageformat=fmt))
    if covers:
        audio["covr"] = covers
    skipped = [image.image_type for image in images if image.image_type != "cover"]
    if skipped:
        logger.warning("MP4 download tags only support cover images; skipped hidden images: %s", skipped)
    audio.save()


def _write_ogg(path: Path, metadata: dict[str, Any], images: list[DownloadImage]) -> None:
    from mutagen.flac import Picture
    from mutagen.oggvorbis import OggVorbis

    audio = OggVorbis(str(path))
    _set_easy_tags(audio, metadata)
    encoded = []
    for image in images:
        data = _image_bytes(image)
        if not data:
            continue
        pic = Picture()
        pic.type = _PIC_TYPES.get(image.image_type, 0)
        pic.mime = image.mime_type
        pic.desc = image.image_type
        pic.data = data
        encoded.append(base64.b64encode(pic.write()).decode("ascii"))
    if encoded:
        audio["metadata_block_picture"] = encoded
    audio.save()


def prepare_tagged_download(source: Path, track: models.Track, images: list[DownloadImage]) -> Path:
    tmp_path = _copy_to_temp(source)
    metadata = _metadata(track)
    suffix = tmp_path.suffix.lower()
    try:
        if suffix == ".flac":
            _write_flac(tmp_path, metadata, images)
        elif suffix == ".mp3":
            _write_mp3(tmp_path, metadata, images)
        elif suffix in {".m4a", ".mp4", ".aac"}:
            _write_mp4(tmp_path, metadata, images)
        elif suffix == ".ogg":
            _write_ogg(tmp_path, metadata, images)
        else:
            logger.warning("download tag writing unsupported for %s; returning copied file", suffix)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        logger.exception("failed to write download tags: track_id=%s source=%s", track.id, source)
        raise
    return tmp_path
