import pytest

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
            ))
        db.commit()
    finally:
        db.close()

    r = await client.get("/tracks?local=true&sort=recent")
    assert r.status_code == 200
    assert len(r.json()) == 25
