from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from deps import get_db
import models, schemas

router = APIRouter(prefix="/albums", tags=["Albums"])


@router.get("", response_model=list[schemas.AlbumOut])
def list_albums(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    sort: str = Query("default", pattern="^(default|recent)$"),
    db: Session = Depends(get_db)
):
    q = db.query(models.Album)
    if sort == "recent":
        q = q.order_by(models.Album.created_at.desc().nullslast(), models.Album.id.desc())
    else:
        q = q.order_by(models.Album.id.desc())
    return q.offset(skip).limit(limit).all()


@router.get("/count")
def count_albums(db: Session = Depends(get_db)):
    return db.query(models.Album).count()


@router.get("/{album_id}", response_model=schemas.AlbumDetail)
def get_album(album_id: int, db: Session = Depends(get_db)):
    album = (
        db.query(models.Album)
        .options(selectinload(models.Album.tracks))
        .filter(models.Album.id == album_id)
        .first()
    )
    if not album:
        raise HTTPException(404, "专辑不存在")
    return album
