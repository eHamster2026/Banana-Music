import pytest

import models
from database import SessionLocal


@pytest.mark.asyncio
async def test_list_artists_default_includes_more_than_legacy_page_size(client):
    db = SessionLocal()
    try:
        for i in range(25):
            db.add(models.Artist(name=f"Artist {i}", art_color="art-1"))
        db.commit()
    finally:
        db.close()

    r = await client.get("/rest/getArtists")
    assert r.status_code == 200
    assert len(r.json()) == 25


@pytest.mark.asyncio
async def test_artist_tracks_include_featured_artist_credits(client):
    db = SessionLocal()
    try:
        primary = models.Artist(name="Primary", art_color="art-1")
        featured = models.Artist(name="Featured", art_color="art-2")
        db.add_all([primary, featured])
        db.flush()

        track = models.Track(
            title="Collab Track",
            artist_id=primary.id,
            duration_sec=180,
            audio_hash=b"artist-track----",
        )
        db.add(track)
        db.flush()
        db.add(models.TrackArtist(
            track_id=track.id,
            artist_id=featured.id,
            role="featured",
            sort_order=1,
        ))
        db.commit()
        featured_id = featured.id
        track_id = track.id
    finally:
        db.close()

    r = await client.get(f"/rest/getArtistSongs?id={featured_id}")
    assert r.status_code == 200
    assert [item["id"] for item in r.json()] == [track_id]


@pytest.mark.asyncio
async def test_artist_albums_include_featured_artist_credits(client):
    db = SessionLocal()
    try:
        primary = models.Artist(name="Album Primary", art_color="art-1")
        featured = models.Artist(name="Album Featured", art_color="art-2")
        db.add_all([primary, featured])
        db.flush()

        album = models.Album(
            title="Collab Album",
            artist_id=primary.id,
            art_color="art-1",
        )
        db.add(album)
        db.flush()
        db.add(models.AlbumArtist(
            album_id=album.id,
            artist_id=featured.id,
            role="featured",
            sort_order=1,
        ))
        db.commit()
        featured_id = featured.id
        album_id = album.id
    finally:
        db.close()

    r = await client.get(f"/artists/{featured_id}/albums")
    assert r.status_code == 200
    assert [item["id"] for item in r.json()] == [album_id]
