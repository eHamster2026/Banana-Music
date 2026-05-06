from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from deps import get_db, get_optional_user
from services.artist_names import UNKNOWN_ARTIST_NAMES
from services.track_likes import mark_track_likes
import models, schemas
import random

router = APIRouter(prefix="/home", tags=["Home"])


def playlist_out(p: models.Playlist) -> schemas.PlaylistOut:
    return schemas.PlaylistOut(
        id=p.id, name=p.name, art_color=p.art_color,
        description=p.description, is_featured=p.is_featured,
        is_system=p.is_system,
        track_count=len(p.playlist_tracks)
    )


@router.get("", response_model=schemas.HomeResponse)
def home(db: Session = Depends(get_db), user=Depends(get_optional_user)):
    banners = db.query(models.Banner).filter(models.Banner.is_active == True)\
        .order_by(models.Banner.sort_order).all()

    all_albums = db.query(models.Album).all()
    random.shuffle(all_albums)

    recommendations = all_albums[:7]
    new_releases = sorted(all_albums, key=lambda a: a.release_date or "", reverse=True)[:6]

    featured = db.query(models.Playlist).filter(models.Playlist.is_featured == True).limit(6).all()

    top_artists = db.query(models.Artist)\
        .filter(models.Artist.name.notin_(UNKNOWN_ARTIST_NAMES))\
        .order_by(models.Artist.monthly_listeners.desc()).limit(8).all()

    local_tracks = db.query(models.Track)\
        .filter(models.Track.is_local.is_(True))\
        .all()
    mark_track_likes(db, local_tracks, user)

    return schemas.HomeResponse(
        banners=banners,
        recommendations=recommendations,
        featured_playlists=[playlist_out(p) for p in featured],
        new_releases=new_releases,
        top_artists=top_artists,
        local_tracks=local_tracks,
    )
