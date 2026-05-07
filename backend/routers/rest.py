import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from starlette.background import BackgroundTask
from sqlalchemy import case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased, joinedload, selectinload

from config import settings
from deps import get_admin_user, get_current_user, get_db, get_optional_user
import models
import schemas
from routers import (
    admin,
    auth,
    home,
    plugins as plugins_router,
    queue as queue_router,
    upload,
)
from plugins.errors import PluginParseError, PluginUpstreamError
from services.artist_names import UNKNOWN_ARTIST_NAMES
from services.plugin_search import run_plugin_search_flat
from services.download_tags import DownloadImage, prepare_tagged_download
from services.track_likes import mark_track_like, mark_track_likes
from services.track_load_options import track_out_load_options


router = APIRouter(prefix="/rest", tags=["Rest"])

_PLAYLIST_NAME_UNIQUE_INDEX = "uq_playlists_user_id_lower_name"
_SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _is_playlist_name_unique_violation(exc: IntegrityError) -> bool:
    raw = str(getattr(exc, "orig", exc)).lower()
    if "unique" not in raw:
        return False
    return _PLAYLIST_NAME_UNIQUE_INDEX.lower() in raw or "playlists" in raw


def _commit_or_duplicate_playlist_name(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _is_playlist_name_unique_violation(exc):
            raise HTTPException(409, "已存在同名歌单")
        raise


def _playlist_out(p: models.Playlist) -> schemas.PlaylistOut:
    return schemas.PlaylistOut(
        id=p.id,
        name=p.name,
        art_color=p.art_color,
        description=p.description,
        is_featured=p.is_featured,
        is_system=p.is_system,
        track_count=len(p.playlist_tracks),
    )


def _playlist_detail(p: models.Playlist) -> schemas.PlaylistDetail:
    tracks = [pt.track for pt in p.playlist_tracks]
    return schemas.PlaylistDetail(
        id=p.id,
        name=p.name,
        art_color=p.art_color,
        description=p.description,
        is_featured=p.is_featured,
        is_system=p.is_system,
        track_count=len(tracks),
        tracks=tracks,
    )


def _bytes_hex(value: bytes | bytearray | memoryview | None) -> str | None:
    if value is None:
        return None
    return bytes(value).hex()


def _artist_export(artist: models.Artist | None) -> dict[str, Any] | None:
    if not artist:
        return None
    return {
        "name": artist.name,
        "ext": artist.ext or {},
    }


def _album_export(album: models.Album | None) -> dict[str, Any] | None:
    if not album:
        return None
    return {
        "title": album.title,
        "artist": _artist_export(album.artist),
        "featured_artists": [_artist_export(artist) for artist in album.featured_artists if _artist_export(artist)],
        "release_date": album.release_date,
        "album_type": album.album_type,
        "ext": album.ext or {},
    }


def _cover_hash_from_path(cover_path: str | None) -> str | None:
    if not cover_path:
        return None
    stem = Path(cover_path).stem
    if _SHA256_HEX_RE.fullmatch(stem):
        return stem.lower()
    path = _cover_file_from_path(cover_path)
    if not path or not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _track_export(track: models.Track, position: int) -> dict[str, Any]:
    cover_path = track.cover_path or (track.album.cover_path if track.album else None)
    return {
        "position": position,
        "audio_hash": _bytes_hex(track.audio_hash),
        "audio_fingerprint": _bytes_hex(track.audio_fingerprint),
        "cover_hash": _cover_hash_from_path(cover_path),
        "title": track.title,
        "duration_sec": track.duration_sec,
        "track_number": track.track_number,
        "lyrics": track.lyrics,
        "artist": _artist_export(track.artist),
        "featured_artists": [_artist_export(artist) for artist in track.featured_artists if _artist_export(artist)],
        "album": _album_export(track.album),
        "ext": track.ext or {},
    }


def _playlist_export_payload(playlist: models.Playlist) -> dict[str, Any]:
    tracks = [
        _track_export(item.track, item.position if item.position is not None else index)
        for index, item in enumerate(playlist.playlist_tracks)
    ]
    return {
        "schema": "banana-playlist.v1",
        "exported_at": models.utcnow(),
        "playlist": {
            "name": playlist.name,
            "description": playlist.description,
        },
        "tracks": tracks,
    }


def _playlist_export_filename(name: str) -> str:
    safe = re.sub(r'[\\/\x00-\x1f<>:"|?*]+', "_", (name or "").strip()).strip(" ._")
    if not safe:
        safe = "playlist"
    return f"{safe[:120]}.banana-playlist.json"


def _safe_download_stem(value: str) -> str:
    return re.sub(r'[\\/\x00-\x1f<>:"|?*]+', "_", value).strip(" ._")


def _track_download_filename(track: models.Track, local: Path) -> str:
    title = _safe_download_stem((track.title or "").strip()) or f"track-{track.id}"
    artist = _safe_download_stem((track.artist.name if track.artist else "").strip())
    stem = f"{title} - {artist}" if artist else title
    suffix = local.suffix or ".flac"
    return f"{stem[:180]}{suffix}"


def _local_file_from_stream_url(stream_url: str | None) -> Path | None:
    if not stream_url or not stream_url.startswith("/resource/"):
        return None
    name = stream_url.removeprefix("/resource/")
    return Path(__file__).parent.parent.parent / "data" / "resource" / name


def _search_patterns(query: str) -> tuple[str, str, str]:
    needle = query.strip().casefold()
    return needle, f"{needle}%", f"%{needle}%"


def _rank_text(column, *, exact: str, prefix: str, contains: str, base: int):
    lowered = func.lower(column)
    return (
        (lowered == exact, base),
        (lowered.like(prefix), base + 1),
        (lowered.like(contains), base + 2),
    )


def _rank_case(*ranked_conditions, else_: int = 999):
    whens = []
    for conditions in ranked_conditions:
        whens.extend(conditions)
    return case(*whens, else_=else_)


def _cover_file_from_path(cover_path: str | None) -> Path | None:
    if not cover_path:
        return None
    return Path(__file__).parent.parent.parent / "data" / "covers" / cover_path


def _mime_from_cover_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "image/jpeg"


# ── System-ish endpoints ────────────────────────────────────────


@router.get("/ping")
def ping():
    return {"status": "ok", "version": "banana-rest-1"}


@router.get("/getLicense")
def get_license():
    return {"valid": True}


# ── Songs ───────────────────────────────────────────────────────


@router.get("/getSongs", response_model=list[schemas.TrackOut])
def get_songs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    sort: str = Query("default", pattern="^(default|recent)$"),
    local: bool = Query(False),
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_optional_user),
):
    q = db.query(models.Track).options(*track_out_load_options())
    if local:
        q = q.filter(models.Track.is_local.is_(True))
    if sort == "recent":
        q = q.order_by(models.Track.created_at.desc().nullslast(), models.Track.id.desc())
    else:
        q = q.order_by(models.Track.id.desc())
    tracks = q.offset(skip).limit(limit).all()
    return mark_track_likes(db, tracks, user)


@router.get("/getSongCount")
def get_song_count(local: bool = Query(False), db: Session = Depends(get_db)):
    q = db.query(models.Track)
    if local:
        q = q.filter(models.Track.is_local.is_(True))
    return q.count()


@router.get("/getSong", response_model=schemas.TrackDetail)
def get_song(
    id: int = Query(...),
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_optional_user),
):
    track = db.query(models.Track).filter(models.Track.id == id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    return mark_track_like(db, track, user)


@router.get("/getStreamInfo")
def get_stream_info(id: int = Query(...), db: Session = Depends(get_db)):
    track = db.query(models.Track).filter(models.Track.id == id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    return {
        "track_id": id,
        "stream_url": f"/rest/stream?id={id}",
        "expires_in": 3600,
    }


@router.get("/stream")
def stream(id: int = Query(...), db: Session = Depends(get_db)):
    track = db.query(models.Track).filter(models.Track.id == id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")

    local = _local_file_from_stream_url(track.stream_url)
    if local and local.exists():
        return FileResponse(local)
    if track.stream_url:
        return RedirectResponse(track.stream_url)
    return RedirectResponse(
        f"https://www.soundhelix.com/examples/mp3/SoundHelix-Song-{(id % 17) + 1}.mp3"
    )


@router.get("/download")
def download(id: int = Query(...), db: Session = Depends(get_db)):
    track = (
        db.query(models.Track)
        .options(
            joinedload(models.Track.artist),
            joinedload(models.Track.album).joinedload(models.Album.artist),
            selectinload(models.Track.track_artists).joinedload(models.TrackArtist.artist),
        )
        .filter(models.Track.id == id)
        .first()
    )
    if not track:
        raise HTTPException(404, "歌曲不存在")
    local = _local_file_from_stream_url(track.stream_url)
    if not local or not local.exists():
        raise HTTPException(404, "文件不存在")
    image_records = (
        db.query(models.MediaImage)
        .filter(
            or_(
                (models.MediaImage.entity_type == "track") & (models.MediaImage.entity_id == track.id),
                (models.MediaImage.entity_type == "album") & (models.MediaImage.entity_id == track.album_id),
            )
        )
        .order_by(models.MediaImage.id)
        .all()
    )
    images: list[DownloadImage] = []
    seen_images: set[tuple[str, str]] = set()

    def add_image(path_value: str | None, image_type: str, mime_type: str | None = None) -> None:
        if not path_value:
            return
        key = (image_type, path_value)
        if key in seen_images:
            return
        path = _cover_file_from_path(path_value)
        if not path or not path.exists():
            return
        seen_images.add(key)
        images.append(DownloadImage(path=path, image_type=image_type, mime_type=mime_type or _mime_from_cover_path(path_value)))

    add_image(track.cover_path or (track.album.cover_path if track.album else None), "cover")
    for record in image_records:
        add_image(record.path, record.image_type, record.mime_type)

    try:
        tagged = prepare_tagged_download(local, track, images)
    except Exception as exc:
        raise HTTPException(500, f"下载标签写入失败: {type(exc).__name__}")
    return FileResponse(
        tagged,
        filename=_track_download_filename(track, local),
        background=BackgroundTask(lambda: tagged.unlink(missing_ok=True)),
    )


@router.get("/getLyrics")
def get_lyrics(id: int = Query(...), db: Session = Depends(get_db)):
    track = db.query(models.Track).filter(models.Track.id == id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    return {"track_id": id, "lyrics": track.lyrics or "（暂无歌词）"}


@router.get("/getCoverArt")
def get_cover_art(
    id: int = Query(...),
    type: str = Query("track", pattern="^(track|album)$"),
    db: Session = Depends(get_db),
):
    cover_path: str | None = None
    if type == "album":
        album = db.query(models.Album).filter(models.Album.id == id).first()
        if not album:
            raise HTTPException(404, "专辑不存在")
        cover_path = album.cover_path
    else:
        track = db.query(models.Track).filter(models.Track.id == id).first()
        if not track:
            raise HTTPException(404, "歌曲不存在")
        cover_path = track.cover_path or (track.album.cover_path if track.album else None)

    cover = _cover_file_from_path(cover_path)
    if not cover or not cover.exists():
        raise HTTPException(404, "封面不存在")
    return FileResponse(cover)


# ── Albums / artists ────────────────────────────────────────────


@router.get("/getAlbumList2", response_model=list[schemas.AlbumOut])
def get_album_list2(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    sort: str = Query("default", pattern="^(default|recent|newest|random)$"),
    db: Session = Depends(get_db),
):
    q = db.query(models.Album)
    if sort in ("recent", "newest"):
        q = q.order_by(models.Album.created_at.desc().nullslast(), models.Album.id.desc())
    elif sort == "random":
        q = q.order_by(func.random())
    else:
        q = q.order_by(models.Album.id.desc())
    return q.offset(skip).limit(limit).all()


@router.get("/getAlbumCount")
def get_album_count(db: Session = Depends(get_db)):
    return db.query(models.Album).count()


@router.get("/getAlbum", response_model=schemas.AlbumDetail)
def get_album(
    id: int = Query(...),
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_optional_user),
):
    album = (
        db.query(models.Album)
        .options(selectinload(models.Album.tracks))
        .filter(models.Album.id == id)
        .first()
    )
    if not album:
        raise HTTPException(404, "专辑不存在")
    mark_track_likes(db, list(album.tracks), user)
    return album


@router.get("/getArtists", response_model=list[schemas.ArtistOut])
def get_artists(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.Artist)
        .filter(models.Artist.name.notin_(UNKNOWN_ARTIST_NAMES))
        .order_by(models.Artist.monthly_listeners.desc(), models.Artist.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/getArtistCount")
def get_artist_count(db: Session = Depends(get_db)):
    return db.query(models.Artist).filter(models.Artist.name.notin_(UNKNOWN_ARTIST_NAMES)).count()


@router.get("/getArtist", response_model=schemas.ArtistOut)
def get_artist(id: int = Query(...), db: Session = Depends(get_db)):
    artist = db.query(models.Artist).filter(models.Artist.id == id).first()
    if not artist:
        raise HTTPException(404, "艺人不存在")
    return artist


@router.get("/getArtistAlbums", response_model=list[schemas.AlbumOut])
def get_artist_albums(id: int = Query(...), db: Session = Depends(get_db)):
    return (
        db.query(models.Album)
        .outerjoin(models.AlbumArtist, models.AlbumArtist.album_id == models.Album.id)
        .filter(or_(models.Album.artist_id == id, models.AlbumArtist.artist_id == id))
        .order_by(models.Album.release_date.desc(), models.Album.id.desc())
        .distinct()
        .all()
    )


@router.get("/getArtistSongs", response_model=list[schemas.TrackOut])
def get_artist_songs(
    id: int = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_optional_user),
):
    tracks = (
        db.query(models.Track)
        .options(*track_out_load_options())
        .outerjoin(models.TrackArtist, models.TrackArtist.track_id == models.Track.id)
        .filter(or_(models.Track.artist_id == id, models.TrackArtist.artist_id == id))
        .order_by(models.Track.created_at.desc(), models.Track.id.desc())
        .distinct()
        .offset(skip)
        .limit(limit)
        .all()
    )
    return mark_track_likes(db, tracks, user)


# ── Search ──────────────────────────────────────────────────────


@router.get("/search3", response_model=schemas.SearchResult)
async def search3(
    query: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_optional_user),
):
    exact, prefix, contains = _search_patterns(query)
    if not exact:
        return schemas.SearchResult(tracks=[], albums=[], artists=[], playlists=[], plugin_hits=[])

    track_featured_artist = aliased(models.Artist)
    track_featured_exact = (
        db.query(models.TrackArtist.track_id)
        .join(track_featured_artist, track_featured_artist.id == models.TrackArtist.artist_id)
        .filter(models.TrackArtist.track_id == models.Track.id, func.lower(track_featured_artist.name) == exact)
        .exists()
    )
    track_featured_prefix = (
        db.query(models.TrackArtist.track_id)
        .join(track_featured_artist, track_featured_artist.id == models.TrackArtist.artist_id)
        .filter(models.TrackArtist.track_id == models.Track.id, func.lower(track_featured_artist.name).like(prefix))
        .exists()
    )
    track_featured_contains = (
        db.query(models.TrackArtist.track_id)
        .join(track_featured_artist, track_featured_artist.id == models.TrackArtist.artist_id)
        .filter(models.TrackArtist.track_id == models.Track.id, func.lower(track_featured_artist.name).like(contains))
        .exists()
    )
    track_rank = _rank_case(
        _rank_text(models.Track.title, exact=exact, prefix=prefix, contains=contains, base=0),
        _rank_text(models.Artist.name, exact=exact, prefix=prefix, contains=contains, base=10),
        (
            (track_featured_exact, 20),
            (track_featured_prefix, 21),
            (track_featured_contains, 22),
        ),
        _rank_text(models.Album.title, exact=exact, prefix=prefix, contains=contains, base=30),
    )

    tracks = (
        db.query(models.Track)
        .options(*track_out_load_options())
        .join(models.Artist, models.Artist.id == models.Track.artist_id)
        .outerjoin(models.Album, models.Album.id == models.Track.album_id)
        .filter(or_(
            func.lower(models.Track.title).like(contains),
            func.lower(models.Artist.name).like(contains),
            track_featured_contains,
            func.lower(models.Album.title).like(contains),
        ))
        .order_by(track_rank, models.Track.created_at.desc().nullslast(), models.Track.id.desc())
        .limit(10)
        .all()
    )

    album_featured_artist = aliased(models.Artist)
    album_featured_exact = (
        db.query(models.AlbumArtist.album_id)
        .join(album_featured_artist, album_featured_artist.id == models.AlbumArtist.artist_id)
        .filter(models.AlbumArtist.album_id == models.Album.id, func.lower(album_featured_artist.name) == exact)
        .exists()
    )
    album_featured_prefix = (
        db.query(models.AlbumArtist.album_id)
        .join(album_featured_artist, album_featured_artist.id == models.AlbumArtist.artist_id)
        .filter(models.AlbumArtist.album_id == models.Album.id, func.lower(album_featured_artist.name).like(prefix))
        .exists()
    )
    album_featured_contains = (
        db.query(models.AlbumArtist.album_id)
        .join(album_featured_artist, album_featured_artist.id == models.AlbumArtist.artist_id)
        .filter(models.AlbumArtist.album_id == models.Album.id, func.lower(album_featured_artist.name).like(contains))
        .exists()
    )
    album_rank = _rank_case(
        _rank_text(models.Album.title, exact=exact, prefix=prefix, contains=contains, base=0),
        _rank_text(models.Artist.name, exact=exact, prefix=prefix, contains=contains, base=10),
        (
            (album_featured_exact, 20),
            (album_featured_prefix, 21),
            (album_featured_contains, 22),
        ),
    )
    albums = (
        db.query(models.Album)
        .join(models.Artist, models.Artist.id == models.Album.artist_id)
        .filter(or_(
            func.lower(models.Album.title).like(contains),
            func.lower(models.Artist.name).like(contains),
            album_featured_contains,
        ))
        .order_by(album_rank, models.Album.created_at.desc().nullslast(), models.Album.id.desc())
        .limit(8)
        .all()
    )
    artist_rank = _rank_case(_rank_text(models.Artist.name, exact=exact, prefix=prefix, contains=contains, base=0))
    artists = (
        db.query(models.Artist)
        .filter(func.lower(models.Artist.name).like(contains), models.Artist.name.notin_(UNKNOWN_ARTIST_NAMES))
        .order_by(artist_rank, models.Artist.id.desc())
        .limit(6)
        .all()
    )
    playlist_rank = _rank_case(_rank_text(models.Playlist.name, exact=exact, prefix=prefix, contains=contains, base=0))
    playlists = (
        db.query(models.Playlist)
        .filter(func.lower(models.Playlist.name).like(contains))
        .order_by(playlist_rank, models.Playlist.created_at.desc().nullslast(), models.Playlist.id.desc())
        .limit(6)
        .all()
    )

    plugin_hits: list[schemas.PluginSearchHitOut] = []
    if user is not None and not settings.banana_testing:
        try:
            raw = await run_plugin_search_flat(query, limit=10)
            plugin_hits = [schemas.PluginSearchHitOut(**d) for d in raw]
        except (PluginUpstreamError, PluginParseError, Exception):
            plugin_hits = []

    return schemas.SearchResult(
        tracks=mark_track_likes(db, tracks, user),
        albums=albums,
        artists=artists,
        playlists=[_playlist_out(p) for p in playlists],
        plugin_hits=plugin_hits,
    )


# ── Stars / history ─────────────────────────────────────────────


def _star_target(
    *,
    id: int | None,
    albumId: int | None,
    artistId: int | None,
) -> tuple[str, int]:
    targets = [
        ("track", id),
        ("album", albumId),
        ("artist", artistId),
    ]
    present = [(kind, value) for kind, value in targets if value is not None]
    if len(present) != 1:
        raise HTTPException(400, "必须且只能提供 id、albumId、artistId 之一")
    return present[0]


def _starred_tracks(db: Session, user_id: int) -> list[models.Track]:
    likes = (
        db.query(models.UserTrackLike)
        .filter(models.UserTrackLike.user_id == user_id)
        .order_by(models.UserTrackLike.liked_at.desc())
        .all()
    )
    return [like.track for like in likes]


def _starred_albums(db: Session, user_id: int) -> list[models.Album]:
    entries = (
        db.query(models.UserLibraryAlbum)
        .filter(models.UserLibraryAlbum.user_id == user_id)
        .order_by(models.UserLibraryAlbum.album_id.desc())
        .all()
    )
    return [entry.album for entry in entries]


def _starred_artists(db: Session, user_id: int) -> list[models.Artist]:
    entries = (
        db.query(models.UserLibraryArtist)
        .join(models.Artist, models.Artist.id == models.UserLibraryArtist.artist_id)
        .filter(models.UserLibraryArtist.user_id == user_id)
        .filter(models.Artist.name.notin_(UNKNOWN_ARTIST_NAMES))
        .order_by(models.UserLibraryArtist.artist_id.desc())
        .all()
    )
    return [entry.artist for entry in entries]


def _set_starred(
    db: Session,
    user_id: int,
    kind: str,
    target_id: int,
    starred: bool | None,
) -> dict:
    if kind == "track":
        if not db.query(models.Track).filter(models.Track.id == target_id).first():
            raise HTTPException(404, "歌曲不存在")
        existing = db.query(models.UserTrackLike).filter_by(user_id=user_id, track_id=target_id).first()
        if starred is None:
            starred = existing is None
        if starred and not existing:
            db.add(models.UserTrackLike(user_id=user_id, track_id=target_id))
        elif not starred and existing:
            db.delete(existing)
        db.commit()
        return {"track_id": target_id, "liked": starred}

    if kind == "album":
        if not db.query(models.Album).filter(models.Album.id == target_id).first():
            raise HTTPException(404, "专辑不存在")
        existing = db.query(models.UserLibraryAlbum).filter_by(user_id=user_id, album_id=target_id).first()
        if starred is None:
            starred = existing is None
        if starred and not existing:
            db.add(models.UserLibraryAlbum(user_id=user_id, album_id=target_id))
        elif not starred and existing:
            db.delete(existing)
        db.commit()
        return {"album_id": target_id, "in_library": starred}

    if not db.query(models.Artist).filter(models.Artist.id == target_id).first():
        raise HTTPException(404, "艺人不存在")
    existing = db.query(models.UserLibraryArtist).filter_by(user_id=user_id, artist_id=target_id).first()
    if starred is None:
        starred = existing is None
    if starred and not existing:
        db.add(models.UserLibraryArtist(user_id=user_id, artist_id=target_id))
    elif not starred and existing:
        db.delete(existing)
    db.commit()
    return {"artist_id": target_id, "in_library": starred}


@router.get("/getStarred2")
def get_starred2(
    includeMeta: bool = Query(False, description="true 时返回 tracks/albums/artists 三类收藏；默认仅返回曲目列表以兼容前端"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    tracks = _starred_tracks(db, user.id)
    mark_track_likes(db, tracks, user)
    if not includeMeta:
        return [schemas.TrackOut.model_validate(track) for track in tracks]
    return {
        "tracks": [schemas.TrackOut.model_validate(track) for track in tracks],
        "albums": [schemas.AlbumOut.model_validate(album) for album in _starred_albums(db, user.id)],
        "artists": [schemas.ArtistOut.model_validate(artist) for artist in _starred_artists(db, user.id)],
    }


@router.post("/toggleStar")
def toggle_star(
    id: int | None = Query(None),
    albumId: int | None = Query(None),
    artistId: int | None = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    kind, target_id = _star_target(id=id, albumId=albumId, artistId=artistId)
    return _set_starred(db, user.id, kind, target_id, starred=None)


@router.post("/star")
def star(
    id: int | None = Query(None),
    albumId: int | None = Query(None),
    artistId: int | None = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    kind, target_id = _star_target(id=id, albumId=albumId, artistId=artistId)
    result = _set_starred(db, user.id, kind, target_id, starred=True)
    return {"message": "已收藏", **result}


@router.post("/unstar")
def unstar(
    id: int | None = Query(None),
    albumId: int | None = Query(None),
    artistId: int | None = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    kind, target_id = _star_target(id=id, albumId=albumId, artistId=artistId)
    result = _set_starred(db, user.id, kind, target_id, starred=False)
    return {"message": "已取消收藏", **result}


@router.post("/scrobble")
def scrobble(
    id: Optional[int] = Query(None),
    body: dict = Body(default_factory=dict),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    track_id = id or body.get("track_id")
    track = db.query(models.Track).filter(models.Track.id == track_id).first()
    if not track:
        return {"message": "歌曲不存在，已忽略"}
    db.add(models.PlayHistory(user_id=user.id, track_id=track.id))
    db.commit()
    return {"message": "已记录"}


# ── Playlists / queue ───────────────────────────────────────────


@router.get("/getPlaylists", response_model=list[schemas.PlaylistOut])
def get_playlists(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    playlists = (
        db.query(models.Playlist)
        .filter(models.Playlist.user_id == user.id)
        .order_by(models.Playlist.created_at.desc())
        .all()
    )
    return [_playlist_out(p) for p in playlists]


@router.get("/getPlaylist", response_model=schemas.PlaylistDetail)
def get_playlist(
    id: int = Query(...),
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_optional_user),
):
    playlist = db.query(models.Playlist).filter(models.Playlist.id == id).first()
    if not playlist:
        raise HTTPException(404, "歌单不存在")
    mark_track_likes(db, [pt.track for pt in playlist.playlist_tracks], user)
    return _playlist_detail(playlist)


@router.get("/exportPlaylist")
def export_playlist(
    id: int = Query(...),
    db: Session = Depends(get_db),
):
    playlist = db.query(models.Playlist).filter(models.Playlist.id == id).first()
    if not playlist:
        raise HTTPException(404, "歌单不存在")
    payload = _playlist_export_payload(playlist)
    filename = _playlist_export_filename(playlist.name)
    encoded = quote(filename)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="playlist.banana-playlist.json"; filename*=UTF-8\'\'{encoded}'
            ),
        },
    )


@router.post("/createPlaylist", response_model=schemas.PlaylistOut)
def create_playlist(
    body: schemas.PlaylistCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "歌单名称不能为空")
    playlist = models.Playlist(
        name=name,
        description=body.description,
        art_color=body.art_color,
        user_id=user.id,
    )
    db.add(playlist)
    _commit_or_duplicate_playlist_name(db)
    db.refresh(playlist)
    return _playlist_out(playlist)


@router.put("/updatePlaylist", response_model=schemas.PlaylistOut)
def update_playlist(
    id: int = Query(...),
    body: schemas.PlaylistUpdate = Body(default_factory=schemas.PlaylistUpdate),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    playlist = (
        db.query(models.Playlist)
        .filter(models.Playlist.id == id, models.Playlist.user_id == user.id)
        .first()
    )
    if not playlist:
        raise HTTPException(404, "歌单不存在或无权限")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "歌单名称不能为空")
        playlist.name = name
    if body.description is not None:
        playlist.description = body.description
    if body.art_color is not None:
        playlist.art_color = body.art_color
    _commit_or_duplicate_playlist_name(db)
    db.refresh(playlist)
    return _playlist_out(playlist)


@router.delete("/deletePlaylist")
def delete_playlist(
    id: int = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    playlist = (
        db.query(models.Playlist)
        .filter(models.Playlist.id == id, models.Playlist.user_id == user.id)
        .first()
    )
    if not playlist:
        raise HTTPException(404, "歌单不存在或无权限")
    db.delete(playlist)
    db.commit()
    return {"message": "已删除"}


@router.post("/addToPlaylist")
def add_to_playlist(
    id: int = Query(...),
    body: schemas.AddTrackToPlaylist = Body(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    playlist = (
        db.query(models.Playlist)
        .filter(models.Playlist.id == id, models.Playlist.user_id == user.id)
        .first()
    )
    if not playlist:
        raise HTTPException(404, "歌单不存在或无权限")
    track = db.query(models.Track).filter(models.Track.id == body.track_id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    existing = db.query(models.PlaylistTrack).filter_by(
        playlist_id=id, track_id=body.track_id
    ).first()
    if existing:
        return {"message": "歌曲已在歌单中"}
    position = len(playlist.playlist_tracks)
    db.add(models.PlaylistTrack(playlist_id=id, track_id=body.track_id, position=position))
    db.commit()
    return {"message": "已添加", "position": position}


@router.delete("/removeFromPlaylist")
def remove_from_playlist(
    id: int = Query(...),
    track_id: int = Query(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    playlist = (
        db.query(models.Playlist)
        .filter(models.Playlist.id == id, models.Playlist.user_id == user.id)
        .first()
    )
    if not playlist:
        raise HTTPException(404, "歌单不存在或无权限")
    pt = db.query(models.PlaylistTrack).filter_by(playlist_id=id, track_id=track_id).first()
    if not pt:
        raise HTTPException(404, "歌曲不在该歌单中")
    db.delete(pt)
    db.commit()
    return {"message": "已移除"}


@router.get("/getPlayQueue", response_model=schemas.QueueStateOut)
def get_play_queue(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = queue_router._get_or_create_queue(db, user.id)
    return queue_router._serialize(q)


# Banana-only APIs live under the new namespace. They are mounted here so the
# old public top-level routes can be removed without rewriting their internals
# all at once.
x_banana = APIRouter(prefix="/x-banana", tags=["Banana Extensions"])
x_banana.include_router(auth.router)
x_banana.include_router(home.router)
x_banana.include_router(upload.router)
x_banana.include_router(admin.router)
x_banana.include_router(plugins_router.router)
x_banana.include_router(queue_router.router)


_ENTITY_MODELS = {
    "track": models.Track,
    "album": models.Album,
    "artist": models.Artist,
}
_IMAGE_TYPES = {"cover", "back", "fanart", "artist"}


def _get_entity(db: Session, entity_type: str, entity_id: int):
    model = _ENTITY_MODELS.get(entity_type)
    if model is None:
        raise HTTPException(400, "entity_type 无效")
    entity = db.query(model).filter(model.id == entity_id).first()
    if not entity:
        raise HTTPException(404, "实体不存在")
    return entity


def _clean_ext(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key, item in value.items():
        text_key = str(key).strip()
        if text_key:
            out[text_key] = item
    return out


def _media_image_out(record: models.MediaImage) -> schemas.MediaImageOut:
    return schemas.MediaImageOut(
        id=record.id,
        entity_type=record.entity_type,
        entity_id=record.entity_id,
        image_type=record.image_type,
        image_url=f"/covers/{record.path}",
        mime_type=record.mime_type,
        created_by_user_id=record.created_by_user_id,
        created_at=record.created_at,
        ext=record.ext or {},
    )


@x_banana.post("/media-images", response_model=schemas.MediaImageOut)
async def create_media_image(
    entity_type: str = Form(...),
    entity_id: int = Form(...),
    image_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    entity_type = entity_type.strip().lower()
    image_type = image_type.strip().lower()
    if image_type not in _IMAGE_TYPES:
        raise HTTPException(400, "image_type 无效")
    _get_entity(db, entity_type, entity_id)

    content_type = (file.content_type or "").lower()
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "图片文件过大")
    if not data:
        raise HTTPException(400, "图片文件为空")
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(400, "文件必须是图片")
    ext = upload._detect_cover_ext(data, content_type)
    if ext not in {".jpg", ".png", ".webp", ".gif"}:
        raise HTTPException(400, "不支持的图片格式")
    path = upload._persist_cover(data, ext)
    if not path:
        raise HTTPException(500, "图片保存失败")
    record = models.MediaImage(
        entity_type=entity_type,
        entity_id=entity_id,
        image_type=image_type,
        path=path,
        mime_type=content_type or _mime_from_cover_path(path),
        created_by_user_id=user.id,
        ext={},
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _media_image_out(record)


@x_banana.get("/media-images", response_model=list[schemas.MediaImageOut])
def list_media_images(
    entity_type: str = Query(..., pattern="^(track|album|artist)$"),
    entity_id: int = Query(...),
    db: Session = Depends(get_db),
):
    _get_entity(db, entity_type, entity_id)
    records = (
        db.query(models.MediaImage)
        .filter(models.MediaImage.entity_type == entity_type, models.MediaImage.entity_id == entity_id)
        .order_by(models.MediaImage.id)
        .all()
    )
    return [_media_image_out(record) for record in records]


@x_banana.patch("/media-images/{image_id}", response_model=schemas.MediaImageOut)
def update_media_image(
    image_id: int,
    body: schemas.MediaImageUpdate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    record = db.get(models.MediaImage, image_id)
    if not record:
        raise HTTPException(404, "图片不存在")
    if body.image_type is not None:
        image_type = body.image_type.strip().lower()
        if image_type not in _IMAGE_TYPES:
            raise HTTPException(400, "image_type 无效")
        record.image_type = image_type
    if body.ext is not None:
        record.ext = _clean_ext(body.ext)
    db.commit()
    db.refresh(record)
    return _media_image_out(record)


@x_banana.delete("/media-images/{image_id}", response_model=dict)
def delete_media_image(
    image_id: int,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    record = db.get(models.MediaImage, image_id)
    if not record:
        raise HTTPException(404, "图片不存在")
    db.delete(record)
    db.commit()
    return {"deleted": True, "image_id": image_id}


@x_banana.get("/metadata-ext/{entity_type}/{entity_id}", response_model=schemas.MetadataExtOut)
def get_metadata_ext(
    entity_type: str,
    entity_id: int,
    db: Session = Depends(get_db),
):
    entity = _get_entity(db, entity_type, entity_id)
    return schemas.MetadataExtOut(entity_type=entity_type, entity_id=entity_id, ext=entity.ext or {})


@x_banana.post("/metadata-ext/{entity_type}/{entity_id}", response_model=schemas.MetadataExtOut)
def add_metadata_ext(
    entity_type: str,
    entity_id: int,
    body: schemas.MetadataExtPatch,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    entity = _get_entity(db, entity_type, entity_id)
    current = dict(entity.ext or {})
    incoming = _clean_ext(body.ext)
    duplicate = sorted(set(current) & set(incoming))
    if duplicate:
        raise HTTPException(409, f"ext key 已存在: {', '.join(duplicate)}")
    entity.ext = {**current, **incoming}
    db.commit()
    db.refresh(entity)
    return schemas.MetadataExtOut(entity_type=entity_type, entity_id=entity_id, ext=entity.ext or {})


@x_banana.put("/metadata-ext/{entity_type}/{entity_id}", response_model=schemas.MetadataExtOut)
def replace_metadata_ext(
    entity_type: str,
    entity_id: int,
    body: schemas.MetadataExtPatch,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    entity = _get_entity(db, entity_type, entity_id)
    entity.ext = _clean_ext(body.ext)
    db.commit()
    db.refresh(entity)
    return schemas.MetadataExtOut(entity_type=entity_type, entity_id=entity_id, ext=entity.ext or {})


@x_banana.patch("/metadata-ext/{entity_type}/{entity_id}", response_model=schemas.MetadataExtOut)
def patch_metadata_ext(
    entity_type: str,
    entity_id: int,
    body: schemas.MetadataExtPatch,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    entity = _get_entity(db, entity_type, entity_id)
    entity.ext = {**dict(entity.ext or {}), **_clean_ext(body.ext)}
    db.commit()
    db.refresh(entity)
    return schemas.MetadataExtOut(entity_type=entity_type, entity_id=entity_id, ext=entity.ext or {})


@x_banana.delete("/metadata-ext/{entity_type}/{entity_id}", response_model=schemas.MetadataExtOut)
def delete_metadata_ext(
    entity_type: str,
    entity_id: int,
    key: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    entity = _get_entity(db, entity_type, entity_id)
    current = dict(entity.ext or {})
    if key:
        current.pop(key, None)
        entity.ext = current
    else:
        entity.ext = {}
    db.commit()
    db.refresh(entity)
    return schemas.MetadataExtOut(entity_type=entity_type, entity_id=entity_id, ext=entity.ext or {})


@x_banana.put("/albums/{album_id}/cover", response_model=schemas.AlbumOut)
def update_album_cover(
    album_id: int,
    req: schemas.AlbumCoverUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    cover_path = upload._cover_path_from_id(req.cover_id)
    album = db.query(models.Album).filter(models.Album.id == album_id).first()
    if not album:
        raise HTTPException(404, "专辑不存在")

    album.cover_path = cover_path
    db.commit()
    db.refresh(album)
    return album


@x_banana.put("/albums/{album_id}/description", response_model=schemas.AlbumOut)
def update_album_description(
    album_id: int,
    req: schemas.AlbumDescriptionUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    album = db.query(models.Album).filter(models.Album.id == album_id).first()
    if not album:
        raise HTTPException(404, "专辑不存在")

    current = dict(album.ext or {})
    text = (req.description or "").strip()
    if text:
        current["description"] = text
    else:
        current.pop("description", None)
    album.ext = current
    db.commit()
    db.refresh(album)
    return album


router.include_router(x_banana)
