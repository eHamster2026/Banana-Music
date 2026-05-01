"""有序艺人名去重与曲目多艺人行写入（track.artist_id 为第一人，其余进 track_artists）。"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

import models


UNKNOWN_ARTIST_NAMES = ("未知艺人", "Unknown Artist")


def is_unknown_artist_name(name: str | None) -> bool:
    return (name or "").strip() in UNKNOWN_ARTIST_NAMES


def dedupe_artist_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in names:
        n = (raw or "").strip()
        if not n or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def artist_names_from_tag_dict(tag: dict | None) -> list[str]:
    if not tag:
        return []
    raw = tag.get("artists")
    if isinstance(raw, list) and raw:
        return dedupe_artist_names([str(x) for x in raw])
    a = tag.get("artist")
    if a and str(a).strip():
        return [str(a).strip()]
    return []


def add_track_featured_artists(
    db: Session,
    track_id: int,
    ordered_names: list[str],
    get_or_create_artist: Callable[[Session, str], models.Artist],
) -> None:
    """ordered_names[0] 已由 track.artist_id 表示，此处只插入后续艺人。"""
    for sort_i, name in enumerate(ordered_names[1:], start=1):
        n = (name or "").strip()
        if not n:
            continue
        art = get_or_create_artist(db, n)
        db.add(
            models.TrackArtist(
                track_id=track_id,
                artist_id=art.id,
                role="featured",
                sort_order=sort_i,
            )
        )
