import pytest

from auth_utils import create_access_token
import models
from database import SessionLocal


@pytest.mark.asyncio
async def test_list_tracks_default_includes_more_than_legacy_page_size(client):
    db = SessionLocal()
    try:
        artist = models.Artist(name="Track Owner", art_color="art-1")
        db.add(artist)
        db.flush()
        for i in range(25):
            db.add(models.Track(
                title=f"Track {i}",
                artist_id=artist.id,
                duration_sec=180,
                stream_url=f"/resource/track-{i}.flac",
                audio_hash=f"track-{i}".encode("ascii").ljust(16, b"-"),
            ))
        db.commit()
    finally:
        db.close()

    r = await client.get("/rest/getSongs")
    assert r.status_code == 200
    assert len(r.json()) == 25


@pytest.mark.asyncio
async def test_get_songs_marks_liked_tracks_for_current_user(client):
    db = SessionLocal()
    try:
        user = models.User(
            username="listener",
            email="listener@example.com",
            hashed_password="x",
        )
        artist = models.Artist(name="Track Owner", art_color="art-1")
        db.add_all([user, artist])
        db.flush()
        liked_track = models.Track(
            title="Liked Track",
            artist_id=artist.id,
            duration_sec=180,
            stream_url="/resource/liked.flac",
            audio_hash=b"liked-track".ljust(16, b"-"),
        )
        other_track = models.Track(
            title="Other Track",
            artist_id=artist.id,
            duration_sec=180,
            stream_url="/resource/other.flac",
            audio_hash=b"other-track".ljust(16, b"-"),
        )
        db.add_all([liked_track, other_track])
        db.flush()
        db.add(models.UserTrackLike(user_id=user.id, track_id=liked_track.id))
        db.commit()
        token = create_access_token({"sub": str(user.id)})
    finally:
        db.close()

    r = await client.get(
        "/rest/getSongs?local=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    by_title = {track["title"]: track for track in r.json()}
    assert by_title["Liked Track"]["is_liked"] is True
    assert by_title["Other Track"]["is_liked"] is False

    anon = await client.get("/rest/getSongs?local=true")
    assert anon.status_code == 200
    assert all(track["is_liked"] is False for track in anon.json())
