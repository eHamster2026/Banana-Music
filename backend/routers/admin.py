"""
routers/admin.py
管理员接口：曲目元数据编辑、文件删除、用户管理。
所有端点需要 is_admin=True。
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from deps import get_db, get_admin_user
from auth_utils import get_password_hash
import models, schemas
from routers.queue import remove_track_from_queues
from services.track_load_options import track_out_load_options
from services.track_metadata_update import update_track_with_metadata_patch

router = APIRouter(prefix="/admin", tags=["Admin"])

RESOURCE_DIR = Path(__file__).parent.parent.parent / "data" / "resource"


# ── 曲目管理 ──────────────────────────────────────────────────

@router.get("/stats", response_model=schemas.LibraryStats)
def library_stats(
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    total_tracks = db.query(models.Track).count()
    total_albums = db.query(models.Album).count()
    total_artists = db.query(models.Artist).count()
    tracks_without_album = (db.query(models.Track)
                            .filter(models.Track.album_id.is_(None)).count())
    tracks_with_unknown_artist = (db.query(models.Track)
                                  .join(models.Artist)
                                  .filter(models.Artist.name == "未知艺人").count())
    tracks_without_stream = (db.query(models.Track)
                             .filter(models.Track.stream_url.is_(None)).count())
    return schemas.LibraryStats(
        total_tracks=total_tracks,
        total_albums=total_albums,
        total_artists=total_artists,
        tracks_without_album=tracks_without_album,
        tracks_with_unknown_artist=tracks_with_unknown_artist,
        tracks_without_stream=tracks_without_stream,
    )


@router.get("/tracks", response_model=schemas.PaginatedTracks)
def list_tracks(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    q: Optional[str] = Query(None),
    missing_metadata: bool = Query(False, description="仅返回元数据不完整的曲目"),
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    query = db.query(models.Track).options(*track_out_load_options())
    if q:
        query = query.filter(models.Track.title.ilike(f"%{q}%"))
    if missing_metadata:
        query = (query.outerjoin(models.Artist)
                 .filter(
                     (models.Track.album_id.is_(None)) |
                     (models.Artist.name == "未知艺人")
                 ))
    total = query.count()
    items = query.order_by(models.Track.id.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@router.post("/tracks/batch-update", response_model=schemas.BatchUpdateOut)
def batch_update_tracks(
    body: schemas.BatchUpdateIn,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    if len(body.updates) > 50:
        raise HTTPException(400, "单次最多 50 条")

    updated = 0
    failed = []

    for item in body.updates:
        patch = schemas.TrackMetadataPatch.model_validate(
            item.model_dump(exclude={"id"})
        )
        try:
            tr = update_track_with_metadata_patch(
                db,
                item.id,
                patch,
                source="admin_batch",
                audit_extra={"admin_username": admin.username},
                flush_in_savepoint=True,
            )
            if tr is None:
                failed.append(schemas.BatchUpdateFailed(id=item.id, reason="曲目不存在"))
                continue
            updated += 1
        except Exception as exc:
            failed.append(schemas.BatchUpdateFailed(id=item.id, reason=str(exc)))
            continue

    db.commit()
    return schemas.BatchUpdateOut(updated=updated, failed=failed)


@router.put("/tracks/{track_id}", response_model=schemas.TrackAdminOut)
def update_track(
    track_id: int,
    body: schemas.TrackAdminUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    track = update_track_with_metadata_patch(
        db,
        track_id,
        body,
        source="admin_put",
        audit_extra={"admin_username": admin.username},
        flush_in_savepoint=False,
    )
    if not track:
        raise HTTPException(404, "曲目不存在")

    db.commit()
    db.refresh(track)
    return track


@router.delete("/tracks/{track_id}/file", response_model=dict)
def delete_track_file(
    track_id: int,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    """仅删除磁盘上的二进制文件，保留数据库元数据（stream_url 置 NULL）。"""
    track = db.query(models.Track).filter(models.Track.id == track_id).first()
    if not track:
        raise HTTPException(404, "曲目不存在")

    deleted = False
    if track.stream_url:
        filename = track.stream_url.lstrip("/resource/").lstrip("resource/")
        filepath = RESOURCE_DIR / filename
        if filepath.exists():
            filepath.unlink()
            deleted = True
        track.stream_url = None
        db.commit()

    return {"deleted": deleted, "track_id": track_id}


@router.delete("/tracks/{track_id}", response_model=dict)
def delete_track(
    track_id: int,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    """删除曲目的全部数据库记录（级联删除关联数据）及磁盘文件。"""
    track = db.query(models.Track).filter(models.Track.id == track_id).first()
    if not track:
        raise HTTPException(404, "曲目不存在")

    # 删除文件
    if track.stream_url:
        filename = track.stream_url.lstrip("/resource/").lstrip("resource/")
        filepath = RESOURCE_DIR / filename
        if filepath.exists():
            filepath.unlink()

    # 删除关联记录
    db.query(models.UserTrackLike).filter(
        models.UserTrackLike.track_id == track_id).delete()
    db.query(models.PlaylistTrack).filter(
        models.PlaylistTrack.track_id == track_id).delete()
    db.query(models.PlayHistory).filter(
        models.PlayHistory.track_id == track_id).delete()
    remove_track_from_queues(db, track_id)
    db.delete(track)
    db.commit()

    return {"deleted": True, "track_id": track_id}


# ── 用户管理 ──────────────────────────────────────────────────

@router.post("/users", response_model=schemas.UserAdminOut)
def create_user(
    body: schemas.UserAdminCreate,
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    if db.query(models.User).filter(models.User.username == body.username).first():
        raise HTTPException(400, "用户名已存在")
    if db.query(models.User).filter(models.User.email == body.email).first():
        raise HTTPException(400, "邮箱已被注册")
    user = models.User(
        username=body.username,
        email=body.email,
        hashed_password=get_password_hash(body.password),
        is_admin=body.is_admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[schemas.UserAdminOut])
def list_users(
    db: Session = Depends(get_db),
    _admin: models.User = Depends(get_admin_user),
):
    return db.query(models.User).order_by(models.User.id).all()


@router.put("/users/{user_id}", response_model=schemas.UserAdminOut)
def update_user(
    user_id: int,
    body: schemas.UserAdminUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")

    if body.username is not None:
        exists = db.query(models.User).filter(
            models.User.username == body.username,
            models.User.id != user_id).first()
        if exists:
            raise HTTPException(400, "用户名已被使用")
        user.username = body.username

    if body.email is not None:
        exists = db.query(models.User).filter(
            models.User.email == body.email,
            models.User.id != user_id).first()
        if exists:
            raise HTTPException(400, "邮箱已被使用")
        user.email = body.email

    if body.is_admin is not None:
        # 不允许撤销自己的管理员权限
        if user_id == admin.id and not body.is_admin:
            raise HTTPException(400, "不能撤销自己的管理员权限")
        user.is_admin = body.is_admin

    db.commit()
    db.refresh(user)
    return user


@router.delete("/users/{user_id}", response_model=dict)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_admin_user),
):
    if user_id == admin.id:
        raise HTTPException(400, "不能删除自己")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "用户不存在")

    db.delete(user)
    db.commit()
    return {"deleted": True, "user_id": user_id}
