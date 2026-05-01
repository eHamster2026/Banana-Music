"""
services/upload_metadata_enrich.py

指纹写入后自动调用流水线 fingerprint_lookup 阶段补全元数据（MusicBrainz 等）。

仅填补明显缺口（未知艺人、无专辑）；需通过 settings.upload_auto_metadata_after_fingerprint 启用。
流水线阶段配置（参与插件、最低置信度）由 data/pipeline.json 控制。
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from config import settings
import models
from app_logging import logger as _app_log
from services.artist_names import add_track_featured_artists, dedupe_artist_names
from services.track_metadata_update import apply_track_metadata_update

logger = logging.getLogger(__name__)

UNKNOWN_ARTIST = "未知艺人"

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


def _get_or_create_album(db: Session, title: str, artist: models.Artist) -> models.Album:
    album = (
        db.query(models.Album)
        .filter(models.Album.title == title, models.Album.artist_id == artist.id)
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


def _needs_enrichment(track: models.Track, artist: Optional[models.Artist]) -> bool:
    if artist is None:
        return True
    if artist.name == UNKNOWN_ARTIST:
        return True
    if track.album_id is None:
        return True
    return False


async def try_enrich_track_from_parse_upload(
    db: Session,
    track_id: int,
    filename_stem: str,
    raw_tags: Optional[dict],
) -> None:
    """
    后台任务：通过 parse_upload 流水线（LLM 等）清洗上传时的文件名/标签，结果写回数据库。

    parse_upload 的性质是「对原始文件标签做清洗」——输入和输出是同一份数据的前后两个版本，
    不是来自外部数据库的陌生数据，因此只要 LLM 有非空结果就直接覆盖，不做保守检查。

    外部 Web 数据（MusicBrainz 等）由 try_enrich_track_from_metadata_plugins 处理，
    那里才需要保守合并。
    """
    if settings.banana_testing:
        return

    from services.pipeline import run_parse_upload
    result = await run_parse_upload(filename_stem, raw_tags)
    if result is None:
        return

    applied: list[str] = []
    _final_title:  list[str] = []   # mutator 写入，供日志读取
    _final_artist: list[str] = []

    def mutator(track: models.Track) -> bool:
        nonlocal applied
        applied = []
        _final_title.clear()
        _final_artist.clear()
        artist = track.artist

        if result.title:
            track.title = result.title.strip()
            applied.append("title")

        best_artist_name = result.artists[0] if result.artists else None
        if best_artist_name:
            merged = dedupe_artist_names(
                [str(x).strip() for x in (result.artists or []) if str(x).strip()]
            )
            if not merged:
                merged = [best_artist_name.strip()]
            primary_name = merged[0]
            new_a = _get_or_create_artist(db, primary_name)
            track.artist_id = new_a.id
            db.flush()
            artist = new_a
            applied.append("artist")
            db.query(models.TrackArtist).filter(
                models.TrackArtist.track_id == track.id
            ).delete(synchronize_session=False)
            if len(merged) > 1:
                add_track_featured_artists(db, track.id, merged, _get_or_create_artist)
                applied.append("featured")

        if result.album and artist is not None:
            alb = _get_or_create_album(db, result.album.strip(), artist)
            if track.album_id != alb.id:
                track.album_id = alb.id
                applied.append("album")

        if result.track_number:
            track.track_number = result.track_number
            applied.append("track_number")

        # 记录最终名称供日志使用
        _final_title.append(track.title or "")
        _final_artist.append(artist.name if artist else "")
        return bool(applied)

    try:
        track = apply_track_metadata_update(
            db,
            track_id,
            mutator,
            source="parse_upload",
            audit_extra={
                "filename_stem": filename_stem,
                "applied_fields": applied,
            },
            flush_in_savepoint=True,
        )
        if track is None:
            return
        title_s  = _final_title[0]  if _final_title  else (track.title or "")
        artist_s = _final_artist[0] if _final_artist else ""
        label = f'#{track_id} "{title_s}"' + (f" / {artist_s}" if artist_s else "")
        if not applied:
            _app_log.info("parse_upload 跳过: %s — LLM 无可用字段", label)
            return
        _app_log.info(
            "parse_upload 完成: %s  fields=[%s]",
            label, ",".join(applied),
        )
    except Exception:
        _app_log.exception("parse_upload enrich failed track_id=%s", track_id)
        try:
            db.rollback()
        except Exception:
            pass


async def try_enrich_track_from_metadata_plugins(db: Session, track: models.Track) -> None:
    """
    指纹后元数据补全。必须使用独立 Session：若在 fingerprint_worker 的同一事务里
    await 网络 I/O，SQLite 连接会长时间占用，易触发其它请求的 database is locked。
    """
    _ = db  # 契约保留；实际读写见下方 SessionLocal

    if not settings.upload_auto_metadata_after_fingerprint:
        return
    if settings.banana_testing:
        return
    fp = track.audio_fingerprint
    dur = int(track.duration_sec) if track.duration_sec else 0
    if not fp or dur <= 0:
        return

    track_id = track.id

    from database import SessionLocal

    s = SessionLocal()
    try:
        t = (
            s.query(models.Track)
            .filter(models.Track.id == track_id)
            .first()
        )
        if not t:
            return

        artist = (
            s.query(models.Artist).filter(models.Artist.id == t.artist_id).first()
        )
        if not _needs_enrichment(t, artist):
            return

        from services.pipeline import run_fingerprint_lookup
        outcome = await run_fingerprint_lookup(fp, dur)

        if outcome is None:
            return

        best, best_conf = outcome

        applied: list[str] = []
        _fp_title:  list[str] = []
        _fp_artist: list[str] = []
        _fp_album:  list[str] = []

        def mutator(t2: models.Track) -> bool:
            nonlocal applied
            applied = []
            _fp_title.clear(); _fp_artist.clear(); _fp_album.clear()
            artist = t2.artist
            if best.title and (artist is None or artist.name == UNKNOWN_ARTIST):
                t2.title = best.title.strip()
                applied.append("title")

            ban = best.artists[0] if best.artists else None
            if ban and (artist is None or artist.name == UNKNOWN_ARTIST):
                new_a = _get_or_create_artist(s, ban.strip())
                t2.artist_id = new_a.id
                s.flush()
                artist = new_a
                applied.append("artist")

            if best.album and t2.album_id is None and artist is not None:
                alb = _get_or_create_album(s, best.album.strip(), artist)
                t2.album_id = alb.id
                applied.append("album")

            if best.lyrics and not (t2.lyrics or "").strip():
                t2.lyrics = best.lyrics.strip() or None
                applied.append("lyrics")

            _fp_title.append(t2.title or "")
            _fp_artist.append(artist.name if artist else "")
            _fp_album.append(best.album.strip() if best.album else "")
            return bool(applied)

        try:
            tr = apply_track_metadata_update(
                s,
                track_id,
                mutator,
                source="fingerprint_lookup",
                audit_extra={
                    "confidence": best_conf,
                    "applied_fields": applied,
                },
                flush_in_savepoint=True,
            )
            if tr is None:
                return
            title_s  = _fp_title[0]  if _fp_title  else (tr.title or "")
            artist_s = _fp_artist[0] if _fp_artist else ""
            label = f'#{track_id} "{title_s}"' + (f" / {artist_s}" if artist_s else "")
            if not applied:
                _app_log.info(
                    "fingerprint_lookup 跳过: %s — 无可用缺口字段 confidence=%.3f",
                    label, best_conf,
                )
                return
            detail: list[str] = []
            if "album" in applied and _fp_album:
                detail.append(f'album="{_fp_album[0]}"')
            if "lyrics" in applied:
                detail.append("lyrics=已写入")
            _app_log.info(
                "fingerprint_lookup 完成: %s  fields=[%s] confidence=%.3f%s",
                label,
                ",".join(applied),
                best_conf,
                "  " + " ".join(detail) if detail else "",
            )
            s.commit()
        except Exception:
            _app_log.exception("upload metadata enrich failed track_id=%s", track_id)
            try:
                s.rollback()
            except Exception:
                pass
    finally:
        s.close()
