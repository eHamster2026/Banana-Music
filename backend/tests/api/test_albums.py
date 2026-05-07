import pytest

import models
from database import SessionLocal
from routers import upload


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


@pytest.mark.asyncio
async def test_update_album_cover_uses_uploaded_cover_id(client, monkeypatch, tmp_path):
    monkeypatch.setattr(upload, "COVER_DIR", tmp_path / "covers")

    registered = await client.post(
        "/rest/x-banana/auth/register",
        json={"username": "cover-user", "email": "cover@example.com", "password": "secret123"},
    )
    assert registered.status_code == 200
    token = registered.json()["access_token"]

    db = SessionLocal()
    try:
        artist = models.Artist(name="Album Cover Owner", art_color="art-1")
        db.add(artist)
        db.flush()
        album = models.Album(title="Needs Cover", artist_id=artist.id, art_color="art-1")
        db.add(album)
        db.commit()
        album_id = album.id
    finally:
        db.close()

    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 16
    uploaded = await client.post(
        "/rest/x-banana/tracks/covers/upload",
        files={"file": ("cover.png", png, "image/png")},
    )
    assert uploaded.status_code == 200
    cover_id = uploaded.json()["cover_id"]

    updated = await client.put(
        f"/rest/x-banana/albums/{album_id}/cover",
        json={"cover_id": cover_id},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert updated.status_code == 200
    assert updated.json()["cover_url"] == f"/covers/{cover_id}"

    db = SessionLocal()
    try:
        album = db.get(models.Album, album_id)
        assert album.cover_path == cover_id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_update_album_description_uses_album_ext(client):
    registered = await client.post(
        "/rest/x-banana/auth/register",
        json={"username": "album-desc-user", "email": "album-desc@example.com", "password": "secret123"},
    )
    assert registered.status_code == 200
    token = registered.json()["access_token"]

    db = SessionLocal()
    try:
        artist = models.Artist(name="Album Description Owner", art_color="art-1")
        db.add(artist)
        db.flush()
        album = models.Album(title="Needs Description", artist_id=artist.id, art_color="art-1")
        db.add(album)
        db.commit()
        album_id = album.id
    finally:
        db.close()

    updated = await client.put(
        f"/rest/x-banana/albums/{album_id}/description",
        json={"description": "  A focused album note.  "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "A focused album note."

    fetched = await client.get(f"/rest/getAlbum?id={album_id}")
    assert fetched.status_code == 200
    assert fetched.json()["description"] == "A focused album note."

    cleared = await client.put(
        f"/rest/x-banana/albums/{album_id}/description",
        json={"description": ""},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cleared.status_code == 200
    assert cleared.json()["description"] is None

    db = SessionLocal()
    try:
        album = db.get(models.Album, album_id)
        assert "description" not in (album.ext or {})
    finally:
        db.close()
