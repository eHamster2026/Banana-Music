from database import SessionLocal
import models
from routers.queue import _serialize, remove_track_from_queues


def _hash(label: str) -> bytes:
    return label.encode("ascii").ljust(16, b"-")[:16]


def _seed_user_and_artist(db):
    user = models.User(
        username="queue-user",
        email="queue-user@example.com",
        hashed_password="x",
    )
    artist = models.Artist(name="Queue Artist", art_color="art-1")
    db.add_all([user, artist])
    db.flush()
    return user, artist


def test_serialize_prunes_stale_queue_items_and_clamps_cursor():
    db = SessionLocal()
    try:
        user, artist = _seed_user_and_artist(db)
        track = models.Track(
            title="Live Track",
            artist_id=artist.id,
            duration_sec=180,
            stream_url="/resource/live.flac",
            audio_hash=_hash("live-track"),
        )
        db.add(track)
        db.flush()
        queue = models.PlayQueue(
            user_id=user.id,
            cursor=1,
            is_playing=True,
            position_sec=12.0,
            updated_at=100,
        )
        db.add(queue)
        db.flush()
        db.add_all([
            models.PlayQueueItem(queue_id=queue.id, track_id=99999, order_idx=0),
            models.PlayQueueItem(queue_id=queue.id, track_id=track.id, order_idx=1),
        ])
        db.commit()

        queue = db.query(models.PlayQueue).filter_by(id=queue.id).first()
        state = _serialize(queue)

        assert state["cursor"] == 0
        assert state["is_playing"] is True
        assert [item["track"]["id"] for item in state["items"]] == [track.id]

        rows = db.query(models.PlayQueueItem).all()
        assert len(rows) == 1
        assert rows[0].track_id == track.id
        assert rows[0].order_idx == 0
    finally:
        db.close()


def test_remove_track_from_queues_pauses_when_current_track_is_deleted():
    db = SessionLocal()
    try:
        user, artist = _seed_user_and_artist(db)
        first = models.Track(
            title="First Track",
            artist_id=artist.id,
            duration_sec=180,
            audio_hash=_hash("first-track"),
        )
        second = models.Track(
            title="Second Track",
            artist_id=artist.id,
            duration_sec=180,
            audio_hash=_hash("second-track"),
        )
        db.add_all([first, second])
        db.flush()
        queue = models.PlayQueue(
            user_id=user.id,
            cursor=0,
            is_playing=True,
            position_sec=8.0,
        )
        db.add(queue)
        db.flush()
        db.add_all([
            models.PlayQueueItem(queue_id=queue.id, track_id=first.id, order_idx=0),
            models.PlayQueueItem(queue_id=queue.id, track_id=second.id, order_idx=1),
        ])
        db.commit()

        remove_track_from_queues(db, first.id)
        db.delete(first)
        db.commit()

        queue = db.query(models.PlayQueue).filter_by(user_id=user.id).first()
        assert queue.cursor == 0
        assert queue.is_playing is False
        assert queue.position_sec == 0.0
        assert [(item.track_id, item.order_idx) for item in queue.items] == [
            (second.id, 0)
        ]
    finally:
        db.close()
