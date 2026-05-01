import pytest

import models
from database import SessionLocal


@pytest.mark.asyncio
async def test_list_albums_default_includes_more_than_legacy_page_size(client):
    db = SessionLocal()
    try:
        artist = models.Artist(name="Album Owner", art_color="art-1")
        db.add(artist)
        db.flush()
        for i in range(25):
            db.add(models.Album(
                title=f"Album {i}",
                artist_id=artist.id,
                art_color="art-1",
            ))
        db.commit()
    finally:
        db.close()

    r = await client.get("/rest/getAlbumList2")
    assert r.status_code == 200
    assert len(r.json()) == 25
