from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from deps import get_db, get_current_user
import models, schemas

router = APIRouter(prefix="/playlists", tags=["Playlists"])

_PLAYLIST_NAME_UNIQUE_INDEX = "uq_playlists_user_id_lower_name"


def _is_playlist_name_unique_violation(exc: IntegrityError) -> bool:
    raw = str(getattr(exc, "orig", exc)).lower()
    if "unique" not in raw:
        return False
    return _PLAYLIST_NAME_UNIQUE_INDEX.lower() in raw or "playlists" in raw


def _commit_or_duplicate_name(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        if _is_playlist_name_unique_violation(e):
            raise HTTPException(409, "已存在同名歌单")
        raise


def playlist_out(p: models.Playlist) -> schemas.PlaylistOut:
    return schemas.PlaylistOut(
        id=p.id, name=p.name, art_color=p.art_color,
        description=p.description, is_featured=p.is_featured,
        is_system=p.is_system, track_count=len(p.playlist_tracks)
    )


def playlist_detail(p: models.Playlist) -> schemas.PlaylistDetail:
    tracks = [pt.track for pt in p.playlist_tracks]
    return schemas.PlaylistDetail(
        id=p.id, name=p.name, art_color=p.art_color,
        description=p.description, is_featured=p.is_featured,
        is_system=p.is_system, track_count=len(tracks), tracks=tracks
    )


@router.get("/{playlist_id}", response_model=schemas.PlaylistDetail)
def get_playlist(playlist_id: int, db: Session = Depends(get_db)):
    p = db.query(models.Playlist).filter(models.Playlist.id == playlist_id).first()
    if not p:
        raise HTTPException(404, "歌单不存在")
    return playlist_detail(p)


@router.post("", response_model=schemas.PlaylistOut)
def create_playlist(
    body: schemas.PlaylistCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    trimmed = body.name.strip()
    if not trimmed:
        raise HTTPException(400, "歌单名称不能为空")
    p = models.Playlist(
        name=trimmed, description=body.description,
        art_color=body.art_color, user_id=user.id
    )
    db.add(p)
    _commit_or_duplicate_name(db)
    db.refresh(p)
    return playlist_out(p)


@router.put("/{playlist_id}", response_model=schemas.PlaylistOut)
def update_playlist(
    playlist_id: int,
    body: schemas.PlaylistUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    p = db.query(models.Playlist).filter(
        models.Playlist.id == playlist_id,
        models.Playlist.user_id == user.id
    ).first()
    if not p:
        raise HTTPException(404, "歌单不存在或无权限")
    if body.name is not None:
        trimmed = body.name.strip()
        if not trimmed:
            raise HTTPException(400, "歌单名称不能为空")
        p.name = trimmed
    if body.description is not None:
        p.description = body.description
    if body.art_color is not None:
        p.art_color = body.art_color
    _commit_or_duplicate_name(db)
    db.refresh(p)
    return playlist_out(p)


@router.delete("/{playlist_id}")
def delete_playlist(
    playlist_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    p = db.query(models.Playlist).filter(
        models.Playlist.id == playlist_id,
        models.Playlist.user_id == user.id
    ).first()
    if not p:
        raise HTTPException(404, "歌单不存在或无权限")
    db.delete(p)
    db.commit()
    return {"message": "已删除"}


@router.post("/{playlist_id}/tracks")
def add_track(
    playlist_id: int,
    body: schemas.AddTrackToPlaylist,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    p = db.query(models.Playlist).filter(
        models.Playlist.id == playlist_id,
        models.Playlist.user_id == user.id
    ).first()
    if not p:
        raise HTTPException(404, "歌单不存在或无权限")
    track = db.query(models.Track).filter(models.Track.id == body.track_id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    existing = db.query(models.PlaylistTrack).filter_by(
        playlist_id=playlist_id, track_id=body.track_id
    ).first()
    if existing:
        return {"message": "歌曲已在歌单中"}
    pos = len(p.playlist_tracks)
    pt = models.PlaylistTrack(playlist_id=playlist_id, track_id=body.track_id, position=pos)
    db.add(pt)
    db.commit()
    return {"message": "已添加", "position": pos}


@router.delete("/{playlist_id}/tracks/{track_id}")
def remove_track(
    playlist_id: int,
    track_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    p = db.query(models.Playlist).filter(
        models.Playlist.id == playlist_id,
        models.Playlist.user_id == user.id
    ).first()
    if not p:
        raise HTTPException(404, "歌单不存在或无权限")
    pt = db.query(models.PlaylistTrack).filter_by(
        playlist_id=playlist_id, track_id=track_id
    ).first()
    if not pt:
        raise HTTPException(404, "歌曲不在该歌单中")
    db.delete(pt)
    db.commit()
    return {"message": "已移除"}
