from typing import Optional

from sqlalchemy.orm import Session

import models


def mark_track_likes(
    db: Session,
    tracks: list[models.Track],
    user: Optional[models.User],
) -> list[models.Track]:
    if not tracks:
        return tracks

    liked_ids: set[int] = set()
    if user is not None:
        track_ids = [track.id for track in tracks if track.id is not None]
        if track_ids:
            liked_ids = {
                row[0]
                for row in (
                    db.query(models.UserTrackLike.track_id)
                    .filter(
                        models.UserTrackLike.user_id == user.id,
                        models.UserTrackLike.track_id.in_(track_ids),
                    )
                    .all()
                )
            }

    for track in tracks:
        track.is_liked = track.id in liked_ids
    return tracks


def mark_track_like(
    db: Session,
    track: models.Track,
    user: Optional[models.User],
) -> models.Track:
    return mark_track_likes(db, [track], user)[0]
