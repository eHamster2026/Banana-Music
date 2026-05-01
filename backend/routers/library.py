from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from deps import get_db, get_current_user
import models, schemas

router = APIRouter(prefix="/library", tags=["Library"])


def playlist_out(p):
    return schemas.PlaylistOut(
        id=p.id, name=p.name, art_color=p.art_color,
        description=p.description, is_featured=p.is_featured,
        is_system=p.is_system, track_count=len(p.playlist_tracks)
    )


# ── Tracks ────────────────────────────────────────────────────────

@router.get("/tracks", response_model=list[schemas.TrackOut])
def liked_tracks(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    likes = db.query(models.UserTrackLike)\
        .filter(models.UserTrackLike.user_id == user.id)\
        .order_by(models.UserTrackLike.liked_at.desc()).all()
    return [like.track for like in likes]


@router.post("/tracks/{track_id}/like", response_model=schemas.TrackLikeStatus)
def toggle_like(
    track_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    track = db.query(models.Track).filter(models.Track.id == track_id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    existing = db.query(models.UserTrackLike).filter_by(
        user_id=user.id, track_id=track_id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"track_id": track_id, "liked": False}
    like = models.UserTrackLike(user_id=user.id, track_id=track_id)
    db.add(like)
    db.commit()
    return {"track_id": track_id, "liked": True}


# ── Albums ────────────────────────────────────────────────────────

@router.get("/albums", response_model=list[schemas.AlbumOut])
def library_albums(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    entries = db.query(models.UserLibraryAlbum)\
        .filter(models.UserLibraryAlbum.user_id == user.id)\
        .options(joinedload(models.UserLibraryAlbum.album))\
        .order_by(models.UserLibraryAlbum.album_id.desc()).all()
    return [e.album for e in entries]


@router.get("/albums/{album_id}")
def album_library_status(
    album_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    entry = db.query(models.UserLibraryAlbum).filter_by(
        user_id=user.id, album_id=album_id
    ).first()
    return {"album_id": album_id, "in_library": entry is not None}


@router.post("/albums/{album_id}")
def toggle_album(
    album_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    album = db.query(models.Album).filter(models.Album.id == album_id).first()
    if not album:
        raise HTTPException(404, "专辑不存在")
    existing = db.query(models.UserLibraryAlbum).filter_by(
        user_id=user.id, album_id=album_id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"album_id": album_id, "in_library": False}
    db.add(models.UserLibraryAlbum(user_id=user.id, album_id=album_id))
    db.commit()
    return {"album_id": album_id, "in_library": True}


# ── Artists ───────────────────────────────────────────────────────

@router.get("/artists", response_model=list[schemas.ArtistOut])
def library_artists(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    entries = db.query(models.UserLibraryArtist)\
        .filter(models.UserLibraryArtist.user_id == user.id)\
        .options(joinedload(models.UserLibraryArtist.artist))\
        .order_by(models.UserLibraryArtist.artist_id.desc()).all()
    return [e.artist for e in entries]


@router.get("/artists/{artist_id}")
def artist_library_status(
    artist_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    entry = db.query(models.UserLibraryArtist).filter_by(
        user_id=user.id, artist_id=artist_id
    ).first()
    return {"artist_id": artist_id, "in_library": entry is not None}


@router.post("/artists/{artist_id}")
def toggle_artist(
    artist_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    artist = db.query(models.Artist).filter(models.Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(404, "艺人不存在")
    existing = db.query(models.UserLibraryArtist).filter_by(
        user_id=user.id, artist_id=artist_id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"artist_id": artist_id, "in_library": False}
    db.add(models.UserLibraryArtist(user_id=user.id, artist_id=artist_id))
    db.commit()
    return {"artist_id": artist_id, "in_library": True}


# ── Playlists ─────────────────────────────────────────────────────

@router.get("/playlists", response_model=list[schemas.PlaylistOut])
def user_playlists(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    playlists = db.query(models.Playlist)\
        .filter(models.Playlist.user_id == user.id)\
        .order_by(models.Playlist.created_at.desc()).all()
    return [playlist_out(p) for p in playlists]
