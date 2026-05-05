import pytest

import models
from database import SessionLocal


def _artist(db, name: str) -> models.Artist:
    artist = models.Artist(name=name, art_color="art-1")
    db.add(artist)
    db.flush()
    return artist


def _album(db, title: str, artist: models.Artist, *, created_at: int = 1) -> models.Album:
    album = models.Album(title=title, artist_id=artist.id, art_color="art-1", created_at=created_at)
    db.add(album)
    db.flush()
    return album


def _track(
    db,
    title: str,
    artist: models.Artist,
    *,
    album: models.Album | None = None,
    created_at: int = 1,
    hash_seed: int = 1,
) -> models.Track:
    track = models.Track(
        title=title,
        artist_id=artist.id,
        album_id=album.id if album else None,
        duration_sec=180,
        created_at=created_at,
        audio_hash=hash_seed.to_bytes(16, "big"),
    )
    db.add(track)
    db.flush()
    return track


@pytest.mark.asyncio
async def test_search_returns_empty_lists(client):
    r = await client.get("/rest/search3?query=x")
    assert r.status_code == 200
    data = r.json()
    assert data["tracks"] == []
    assert data["albums"] == []
    assert data["artists"] == []
    assert data["playlists"] == []
    assert data.get("plugin_hits") == []


@pytest.mark.asyncio
async def test_search_blank_query_after_trim_returns_empty_lists(client):
    db = SessionLocal()
    try:
        artist = _artist(db, "Any Artist")
        _track(db, "Any Song", artist, hash_seed=1)
        db.commit()
    finally:
        db.close()

    r = await client.get("/rest/search3?query=%20%20%20")
    assert r.status_code == 200
    data = r.json()
    assert data["tracks"] == []
    assert data["albums"] == []
    assert data["artists"] == []
    assert data["playlists"] == []
    assert data.get("plugin_hits") == []


@pytest.mark.asyncio
async def test_search_hides_unknown_artist_from_artist_results(client):
    db = SessionLocal()
    try:
        db.add(models.Artist(name="未知艺人", art_color="art-1"))
        db.commit()
    finally:
        db.close()

    r = await client.get("/rest/search3?query=未知")
    assert r.status_code == 200
    assert r.json()["artists"] == []


@pytest.mark.asyncio
async def test_search_orders_tracks_by_text_relevance_before_recency(client):
    db = SessionLocal()
    try:
        artist = _artist(db, "Search Artist")
        _track(db, "Say Hello", artist, created_at=300, hash_seed=1)
        _track(db, "Hello Again", artist, created_at=200, hash_seed=2)
        _track(db, "Hello", artist, created_at=100, hash_seed=3)
        db.commit()
    finally:
        db.close()

    r = await client.get("/rest/search3?query=hello")
    assert r.status_code == 200
    assert [t["title"] for t in r.json()["tracks"][:3]] == ["Hello", "Hello Again", "Say Hello"]


@pytest.mark.asyncio
async def test_search_tracks_match_main_artist_and_album_title(client):
    db = SessionLocal()
    try:
        nujabes = _artist(db, "Nujabes")
        other = _artist(db, "Other Artist")
        album = _album(db, "Modal Soul", other)
        _track(db, "Feather", nujabes, hash_seed=1)
        _track(db, "Ordinary Song", other, album=album, hash_seed=2)
        db.commit()
    finally:
        db.close()

    by_artist = await client.get("/rest/search3?query=nujabes")
    assert by_artist.status_code == 200
    assert [t["title"] for t in by_artist.json()["tracks"]] == ["Feather"]

    by_album = await client.get("/rest/search3?query=modal")
    assert by_album.status_code == 200
    assert [t["title"] for t in by_album.json()["tracks"]] == ["Ordinary Song"]


@pytest.mark.asyncio
async def test_search_albums_match_main_and_featured_artists(client):
    db = SessionLocal()
    try:
        massive = _artist(db, "Massive Attack")
        eno = _artist(db, "Brian Eno")
        other = _artist(db, "Other Artist")
        _album(db, "Blue Lines", massive, created_at=1)
        featured_album = _album(db, "Ambient Works", other, created_at=2)
        db.add(models.AlbumArtist(album_id=featured_album.id, artist_id=eno.id, sort_order=0))
        db.commit()
    finally:
        db.close()

    by_main = await client.get("/rest/search3?query=massive")
    assert by_main.status_code == 200
    assert [a["title"] for a in by_main.json()["albums"]] == ["Blue Lines"]

    by_featured = await client.get("/rest/search3?query=brian")
    assert by_featured.status_code == 200
    assert [a["title"] for a in by_featured.json()["albums"]] == ["Ambient Works"]


@pytest.mark.asyncio
async def test_search_uses_created_at_and_id_as_tiebreakers(client):
    db = SessionLocal()
    try:
        artist = _artist(db, "Tie Artist")
        _track(db, "Morning Mix", artist, created_at=100, hash_seed=1)
        _track(db, "Evening Mix", artist, created_at=200, hash_seed=2)
        _track(db, "Late Mix", artist, created_at=200, hash_seed=3)
        db.commit()
    finally:
        db.close()

    r = await client.get("/rest/search3?query=mix")
    assert r.status_code == 200
    assert [t["title"] for t in r.json()["tracks"][:3]] == ["Late Mix", "Evening Mix", "Morning Mix"]
