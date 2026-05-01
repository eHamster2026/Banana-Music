from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, selectinload

from config import settings
from deps import get_current_user, get_db, get_optional_user
import models
import schemas
from routers import (
    admin,
    auth,
    home,
    plugins as plugins_router,
    queue as queue_router,
    search,
    upload,
)
from plugins.errors import PluginParseError, PluginUpstreamError
from services.plugin_search import run_plugin_search_flat


router = APIRouter(prefix="/rest", tags=["Rest"])


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


def _local_file_from_stream_url(stream_url: str | None) -> Path | None:
    if not stream_url or not stream_url.startswith("/resource/"):
        return None
    name = stream_url.removeprefix("/resource/")
    return Path(__file__).parent.parent.parent / "data" / "resource" / name


def _cover_file_from_path(cover_path: str | None) -> Path | None:
    if not cover_path:
        return None
    return Path(__file__).parent.parent.parent / "data" / "covers" / cover_path


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
):
    q = db.query(models.Track)
    if local:
        q = q.filter(models.Track.stream_url.like("/resource/%"))
    if sort == "recent":
        q = q.order_by(models.Track.created_at.desc().nullslast(), models.Track.id.desc())
    else:
        q = q.order_by(models.Track.id.desc())
    return q.offset(skip).limit(limit).all()


@router.get("/getSongCount")
def get_song_count(local: bool = Query(False), db: Session = Depends(get_db)):
    q = db.query(models.Track)
    if local:
        q = q.filter(models.Track.stream_url.like("/resource/%"))
    return q.count()


@router.get("/getSong", response_model=schemas.TrackDetail)
def get_song(id: int = Query(...), db: Session = Depends(get_db)):
    track = db.query(models.Track).filter(models.Track.id == id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    return track


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
    track = db.query(models.Track).filter(models.Track.id == id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    local = _local_file_from_stream_url(track.stream_url)
    if not local or not local.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(local, filename=local.name)


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
def get_album(id: int = Query(...), db: Session = Depends(get_db)):
    album = (
        db.query(models.Album)
        .options(selectinload(models.Album.tracks))
        .filter(models.Album.id == id)
        .first()
    )
    if not album:
        raise HTTPException(404, "专辑不存在")
    return album


@router.get("/getArtists", response_model=list[schemas.ArtistOut])
def get_artists(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.Artist)
        .order_by(models.Artist.monthly_listeners.desc(), models.Artist.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/getArtistCount")
def get_artist_count(db: Session = Depends(get_db)):
    return db.query(models.Artist).count()


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
):
    return (
        db.query(models.Track)
        .outerjoin(models.TrackArtist, models.TrackArtist.track_id == models.Track.id)
        .filter(or_(models.Track.artist_id == id, models.TrackArtist.artist_id == id))
        .order_by(models.Track.created_at.desc(), models.Track.id.desc())
        .distinct()
        .offset(skip)
        .limit(limit)
        .all()
    )


# ── Search ──────────────────────────────────────────────────────


@router.get("/search3", response_model=schemas.SearchResult)
async def search3(
    query: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    user: Optional[models.User] = Depends(get_optional_user),
):
    like = f"%{query}%"
    featured_track_ids = (
        db.query(models.TrackArtist.track_id)
        .join(models.Artist, models.Artist.id == models.TrackArtist.artist_id)
        .filter(models.Artist.name.ilike(like))
    )
    featured_album_ids = (
        db.query(models.AlbumArtist.album_id)
        .join(models.Artist, models.Artist.id == models.AlbumArtist.artist_id)
        .filter(models.Artist.name.ilike(like))
    )

    tracks = (
        db.query(models.Track)
        .filter(or_(models.Track.title.ilike(like), models.Track.id.in_(featured_track_ids)))
        .limit(10)
        .all()
    )
    albums = (
        db.query(models.Album)
        .filter(or_(models.Album.title.ilike(like), models.Album.id.in_(featured_album_ids)))
        .limit(8)
        .all()
    )
    artists = db.query(models.Artist).filter(models.Artist.name.ilike(like)).limit(6).all()
    playlists = db.query(models.Playlist).filter(models.Playlist.name.ilike(like)).limit(6).all()

    plugin_hits: list[schemas.PluginSearchHitOut] = []
    if user is not None and not settings.banana_testing:
        try:
            raw = await run_plugin_search_flat(query, limit=10)
            plugin_hits = [schemas.PluginSearchHitOut(**d) for d in raw]
        except (PluginUpstreamError, PluginParseError, Exception):
            plugin_hits = []

    return schemas.SearchResult(
        tracks=tracks,
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
        .filter(models.UserLibraryArtist.user_id == user_id)
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
def get_playlist(id: int = Query(...), db: Session = Depends(get_db)):
    playlist = db.query(models.Playlist).filter(models.Playlist.id == id).first()
    if not playlist:
        raise HTTPException(404, "歌单不存在")
    return _playlist_detail(playlist)


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
    db.commit()
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
    db.commit()
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
x_banana.include_router(search.router)
x_banana.include_router(upload.router)
x_banana.include_router(admin.router)
x_banana.include_router(plugins_router.router)
x_banana.include_router(queue_router.router)

router.include_router(x_banana)
