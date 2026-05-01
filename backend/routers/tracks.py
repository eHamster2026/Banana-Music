from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from deps import get_db, get_current_user
import models, schemas

router = APIRouter(prefix="/tracks", tags=["Tracks"])


@router.get("", response_model=list[schemas.TrackOut])
def list_tracks(
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


@router.get("/count")
def count_tracks(
    local: bool = Query(False),
    db: Session = Depends(get_db),
):
    q = db.query(models.Track)
    if local:
        q = q.filter(models.Track.stream_url.like("/resource/%"))
    return q.count()


@router.get("/{track_id}", response_model=schemas.TrackDetail)
def get_track(track_id: int, db: Session = Depends(get_db)):
    track = db.query(models.Track).filter(models.Track.id == track_id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    return track


@router.get("/{track_id}/stream")
def get_stream(track_id: int, db: Session = Depends(get_db)):
    track = db.query(models.Track).filter(models.Track.id == track_id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    return {
        "track_id": track_id,
        "stream_url": track.stream_url or f"https://www.soundhelix.com/examples/mp3/SoundHelix-Song-{(track_id % 17) + 1}.mp3",
        "expires_in": 3600,
    }


@router.get("/{track_id}/lyrics")
def get_lyrics(track_id: int, db: Session = Depends(get_db)):
    track = db.query(models.Track).filter(models.Track.id == track_id).first()
    if not track:
        raise HTTPException(404, "歌曲不存在")
    return {"track_id": track_id, "lyrics": track.lyrics or "（暂无歌词）"}
