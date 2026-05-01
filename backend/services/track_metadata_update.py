"""
曲目表（tracks）元数据写入的统一入口：所有会改库内曲目元数据的逻辑应通过
`apply_track_metadata_update` 完成 flush，并在此追加 `data/logs/metadata_changes.jsonl` 审计行。

管理端单首/批量、插件等若只做「标题/艺人/专辑/…」式补丁，应使用
`update_track_with_metadata_patch`（内部仍走同一审计路径）。
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, joinedload, selectinload

from config import settings
import models
import schemas

_lock = threading.Lock()
MAX_JSON_STR = 4000

_log_path_fn: Callable[[], Path]


def _default_log_path() -> Path:
    root = Path(__file__).resolve().parent.parent.parent
    return root / "data" / "logs" / "metadata_changes.jsonl"


_log_path_fn = _default_log_path


def load_track_for_audit(db: Session, track_id: int) -> models.Track | None:
    return (
        db.query(models.Track)
        .options(
            joinedload(models.Track.artist),
            joinedload(models.Track.album),
            selectinload(models.Track.track_artists).joinedload(
                models.TrackArtist.artist
            ),
        )
        .filter(models.Track.id == track_id)
        .first()
    )


def _truncate(s: str | None) -> str | None:
    if s is None:
        return None
    if len(s) <= MAX_JSON_STR:
        return s
    return s[:MAX_JSON_STR] + f"...[truncated,len={len(s)}]"


def track_metadata_snapshot(track: models.Track) -> dict[str, Any]:
    featured: list[str] = []
    try:
        tas = list(track.track_artists or [])
        tas.sort(key=lambda x: x.sort_order)
        for ta in tas:
            if ta.artist:
                featured.append(ta.artist.name)
    except Exception:
        pass
    return {
        "title": track.title,
        "artist_id": track.artist_id,
        "artist_name": track.artist.name if track.artist else None,
        "album_id": track.album_id,
        "album_title": track.album.title if track.album else None,
        "track_number": track.track_number,
        "duration_sec": track.duration_sec,
        "lyrics": _truncate(track.lyrics),
        "featured_artist_names": featured,
    }


def diff_metadata(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    changes: dict[str, dict[str, Any]] = {}
    keys = set(before) | set(after)
    for k in keys:
        if before.get(k) != after.get(k):
            changes[k] = {"before": before.get(k), "after": after.get(k)}
    return changes


def _append_metadata_audit_file(
    *,
    source: str,
    track_id: int,
    track_title: str | None = None,
    changes: dict[str, dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> None:
    if settings.banana_testing:
        return
    if not changes:
        return
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "track_id": track_id,
    }
    if track_title:
        record["track_title"] = track_title
    record["changes"] = changes
    if extra:
        record["extra"] = extra
    path = _log_path_fn()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)


# 别名：单元测试与直接写审计文件场景（业务代码请只用 apply_track_metadata_update）
log_metadata_change = _append_metadata_audit_file


def apply_track_metadata_update(
    db: Session,
    track_id: int,
    mutator: Callable[[models.Track], bool],
    *,
    source: str,
    audit_extra: dict[str, Any] | None = None,
    flush_in_savepoint: bool = False,
) -> models.Track | None:
    """
    加载曲目，对 ORM 实体执行 mutator；若 mutator 返回 True 则 flush（可选 savepoint），
    并按前后快照写入审计文件。返回 mutator 作用过的同一 Track 实例，无此 id 则 None。
    """
    track = load_track_for_audit(db, track_id)
    if not track:
        return None
    before = track_metadata_snapshot(track)
    should_flush = mutator(track)
    if not should_flush:
        return track
    if flush_in_savepoint:
        with db.begin_nested():
            db.flush()
    else:
        db.flush()
    track_after = load_track_for_audit(db, track_id)
    if track_after:
        after_snap = track_metadata_snapshot(track_after)
        changes = diff_metadata(before, after_snap)
        _append_metadata_audit_file(
            source=source,
            track_id=track_id,
            track_title=after_snap.get("title") or None,
            changes=changes,
            extra=audit_extra,
        )
    return track


_ART_COLORS = [
    "art-1", "art-2", "art-3", "art-4", "art-5", "art-6",
    "art-7", "art-8", "art-9", "art-10", "art-11", "art-12",
]


def _get_or_create_artist(db: Session, name: str) -> models.Artist:
    artist = db.query(models.Artist).filter(models.Artist.name == name).first()
    if not artist:
        color = _ART_COLORS[db.query(models.Artist).count() % len(_ART_COLORS)]
        artist = models.Artist(
            name=name,
            art_color=color,
            bio=f"{name} 的本地收藏",
            monthly_listeners=0,
        )
        db.add(artist)
        db.flush()
    return artist


def _get_or_create_album(
    db: Session, title: str, artist: models.Artist
) -> models.Album:
    album = (
        db.query(models.Album)
        .filter(
            models.Album.title == title,
            models.Album.artist_id == artist.id,
        )
        .first()
    )
    if not album:
        color = _ART_COLORS[db.query(models.Album).count() % len(_ART_COLORS)]
        album = models.Album(
            title=title,
            artist_id=artist.id,
            art_color=color,
            album_type="album",
        )
        db.add(album)
        db.flush()
    return album


def patch_track_row(
    db: Session,
    track: models.Track,
    patch: schemas.TrackMetadataPatch,
) -> bool:
    """
    按补丁修改已加载的 Track ORM 行（就地）。返回是否至少写入了一个补丁字段。
    """
    changed = False
    if patch.title is not None:
        track.title = patch.title.strip()
        changed = True

    if patch.artist_name is not None:
        artist = _get_or_create_artist(db, patch.artist_name.strip())
        track.artist_id = artist.id
        changed = True

    if patch.album_title is not None:
        if patch.album_title.strip() == "":
            track.album_id = None
        else:
            owner = (
                db.query(models.Artist)
                .filter(models.Artist.id == track.artist_id)
                .first()
            )
            album = _get_or_create_album(db, patch.album_title.strip(), owner)
            track.album_id = album.id
        changed = True

    if patch.track_number is not None:
        track.track_number = patch.track_number
        changed = True

    if patch.duration_sec is not None:
        track.duration_sec = patch.duration_sec
        changed = True

    if patch.lyrics is not None:
        lyrics = patch.lyrics.strip()
        track.lyrics = lyrics or None
        changed = True

    return changed


def update_track_with_metadata_patch(
    db: Session,
    track_id: int,
    patch: schemas.TrackMetadataPatch,
    *,
    source: str,
    audit_extra: dict[str, Any] | None = None,
    flush_in_savepoint: bool = False,
) -> models.Track | None:
    """
    对指定曲目应用元数据补丁：加载 → patch_track_row → flush（可选 savepoint）→ 审计。
    供管理路由、插件等共用。
    """
    def mutator(t: models.Track) -> bool:
        return patch_track_row(db, t, patch)

    return apply_track_metadata_update(
        db,
        track_id,
        mutator,
        source=source,
        audit_extra=audit_extra,
        flush_in_savepoint=flush_in_savepoint,
    )
