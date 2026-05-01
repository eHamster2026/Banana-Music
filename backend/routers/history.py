from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from deps import get_db, get_current_user
import models, schemas

router = APIRouter(prefix="/history", tags=["History"])


@router.post("/play")
def record_play(
    body: schemas.PlayEvent,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    track = db.query(models.Track).filter(models.Track.id == body.track_id).first()
    if not track:
        return {"message": "歌曲不存在，已忽略"}
    entry = models.PlayHistory(user_id=user.id, track_id=body.track_id)
    db.add(entry)
    db.commit()
    return {"message": "已记录"}


@router.get("", response_model=list[schemas.HistoryItem])
def get_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user)
):
    return db.query(models.PlayHistory)\
        .filter(models.PlayHistory.user_id == user.id)\
        .order_by(models.PlayHistory.played_at.desc())\
        .offset(skip).limit(limit).all()
