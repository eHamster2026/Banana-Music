from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session
from deps import get_db
from services.artist_names import UNKNOWN_ARTIST_NAMES
import models, schemas

router = APIRouter(prefix="/artists", tags=["Artists"])


@router.get("", response_model=list[schemas.ArtistOut])
def list_artists(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db)
):
    return db.query(models.Artist)\
        .filter(models.Artist.name.notin_(UNKNOWN_ARTIST_NAMES))\
        .order_by(models.Artist.monthly_listeners.desc(), models.Artist.id.desc())\
        .offset(skip).limit(limit).all()


@router.get("/count")
def count_artists(db: Session = Depends(get_db)):
    return db.query(models.Artist).filter(models.Artist.name.notin_(UNKNOWN_ARTIST_NAMES)).count()


@router.get("/{artist_id}", response_model=schemas.ArtistOut)
def get_artist(artist_id: int, db: Session = Depends(get_db)):
    artist = db.query(models.Artist).filter(models.Artist.id == artist_id).first()
    if not artist:
        raise HTTPException(404, "艺人不存在")
    return artist


@router.get("/{artist_id}/albums", response_model=list[schemas.AlbumOut])
def artist_albums(artist_id: int, db: Session = Depends(get_db)):
    return (
        db.query(models.Album)
        .outerjoin(models.AlbumArtist, models.AlbumArtist.album_id == models.Album.id)
        .filter(or_(
            models.Album.artist_id == artist_id,
            models.AlbumArtist.artist_id == artist_id,
        ))
        .order_by(models.Album.release_date.desc(), models.Album.id.desc())
        .distinct()
        .all()
    )


@router.get("/{artist_id}/tracks", response_model=list[schemas.TrackOut])
def artist_top_tracks(
    artist_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return (
        db.query(models.Track)
        .outerjoin(models.TrackArtist, models.TrackArtist.track_id == models.Track.id)
        .filter(or_(
            models.Track.artist_id == artist_id,
            models.TrackArtist.artist_id == artist_id,
        ))
        .order_by(models.Track.created_at.desc(), models.Track.id.desc())
        .distinct()
        .offset(skip).limit(limit).all()
    )
