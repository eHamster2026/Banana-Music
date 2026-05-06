import hashlib

import pytest

import models
from database import SessionLocal
from routers import rest


async def _register(client, username: str, email: str) -> str:
    r = await client.post(
        "/rest/x-banana/auth/register",
        json={"username": username, "email": email, "password": "secret123"},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_create_playlist_rejects_duplicate_name(client):
    token = await _register(client, "pluser1", "pl1@example.com")
    h = {"Authorization": f"Bearer {token}"}
    r1 = await client.post(
        "/rest/createPlaylist",
        json={"name": "我的歌单", "art_color": "art-1"},
        headers=h,
    )
    assert r1.status_code == 200
    r2 = await client.post(
        "/rest/createPlaylist",
        json={"name": "我的歌单", "art_color": "art-2"},
        headers=h,
    )
    assert r2.status_code == 409
    assert r2.json()["detail"] == "已存在同名歌单"


@pytest.mark.asyncio
async def test_create_playlist_duplicate_case_insensitive(client):
    token = await _register(client, "pluser2", "pl2@example.com")
    h = {"Authorization": f"Bearer {token}"}
    await client.post(
        "/rest/createPlaylist",
        json={"name": "Rock", "art_color": "art-1"},
        headers=h,
    )
    r = await client.post(
        "/rest/createPlaylist",
        json={"name": "rock", "art_color": "art-2"},
        headers=h,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_different_users_may_use_same_playlist_name(client):
    t1 = await _register(client, "pluser3a", "pl3a@example.com")
    t2 = await _register(client, "pluser3b", "pl3b@example.com")
    r1 = await client.post(
        "/rest/createPlaylist",
        json={"name": "共享名", "art_color": "art-1"},
        headers={"Authorization": f"Bearer {t1}"},
    )
    r2 = await client.post(
        "/rest/createPlaylist",
        json={"name": "共享名", "art_color": "art-2"},
        headers={"Authorization": f"Bearer {t2}"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_update_playlist_rejects_duplicate_name(client):
    token = await _register(client, "pluser4", "pl4@example.com")
    h = {"Authorization": f"Bearer {token}"}
    a = await client.post(
        "/rest/createPlaylist",
        json={"name": "列表 A", "art_color": "art-1"},
        headers=h,
    )
    b = await client.post(
        "/rest/createPlaylist",
        json={"name": "列表 B", "art_color": "art-2"},
        headers=h,
    )
    assert a.status_code == 200 and b.status_code == 200
    bid = b.json()["id"]
    r = await client.put(
        f"/rest/updatePlaylist?id={bid}",
        json={"name": "列表 A"},
        headers=h,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_update_playlist_same_name_ok(client):
    token = await _register(client, "pluser5", "pl5@example.com")
    h = {"Authorization": f"Bearer {token}"}
    a = await client.post(
        "/rest/createPlaylist",
        json={"name": "仅一个", "art_color": "art-1"},
        headers=h,
    )
    assert a.status_code == 200
    pid = a.json()["id"]
    r = await client.put(
        f"/rest/updatePlaylist?id={pid}",
        json={"name": "仅一个", "description": "改描述"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "仅一个"


@pytest.mark.asyncio
async def test_export_playlist_json_includes_hashes_and_metadata(client):
    cover_bytes = b"cover-image"
    cover_hash = hashlib.sha256(cover_bytes).hexdigest()
    db = SessionLocal()
    try:
        artist = models.Artist(name="Export Artist", art_color="art-1", ext={"sort": "artist"})
        feat = models.Artist(name="Featured Export", art_color="art-2")
        album = models.Album(
            title="Export Album",
            artist=artist,
            art_color="art-3",
            cover_path=f"{cover_hash}.jpg",
            release_date="2026-01-02",
            album_type="album",
            ext={"label": "Banana"},
        )
        track_with_hashes = models.Track(
            title="Export One",
            artist=artist,
            album=album,
            duration_sec=123,
            track_number=1,
            lyrics="export lyrics",
            stream_url="/resource/export-one.flac",
            is_local=True,
            audio_hash=bytes.fromhex("00112233445566778899aabbccddeeff"),
            audio_fingerprint=bytes.fromhex("0f10aabb"),
            ext={"work": "BWV 1"},
        )
        track_without_optional = models.Track(
            title="Export Two",
            artist=artist,
            duration_sec=234,
            stream_url="/resource/export-two.flac",
            is_local=True,
            audio_hash=bytes.fromhex("ffeeddccbbaa99887766554433221100"),
        )
        playlist = models.Playlist(name="Export Mix", description="For export", art_color="art-4")
        db.add_all([artist, feat, album, track_with_hashes, track_without_optional, playlist])
        db.flush()
        db.add(models.TrackArtist(
            track_id=track_with_hashes.id,
            artist_id=feat.id,
            role="featured",
            sort_order=0,
        ))
        db.add_all([
            models.PlaylistTrack(playlist_id=playlist.id, track_id=track_with_hashes.id, position=0),
            models.PlaylistTrack(playlist_id=playlist.id, track_id=track_without_optional.id, position=1),
        ])
        db.commit()
        playlist_id = playlist.id
        track_with_hashes_id = track_with_hashes.id
        feat_id = feat.id
    finally:
        db.close()

    response = await client.get("/rest/exportPlaylist", params={"id": playlist_id})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert "attachment" in response.headers["content-disposition"]
    assert "Export%20Mix.banana-playlist.json" in response.headers["content-disposition"]

    data = response.json()
    assert data["schema"] == "banana-playlist.v1"
    assert data["playlist"]["name"] == "Export Mix"
    assert data["playlist"]["track_count"] == 2
    assert [track["position"] for track in data["tracks"]] == [0, 1]

    first = data["tracks"][0]
    assert first["track_id"] == track_with_hashes_id
    assert first["audio_hash"] == "00112233445566778899aabbccddeeff"
    assert first["audio_fingerprint"] == "0f10aabb"
    assert first["cover_hash"] == cover_hash
    assert first["title"] == "Export One"
    assert first["lyrics"] == "export lyrics"
    assert first["artist"]["name"] == "Export Artist"
    assert first["featured_artists"] == [{
        "id": feat_id,
        "name": "Featured Export",
        "art_color": "art-2",
        "ext": {},
    }]
    assert first["album"]["title"] == "Export Album"
    assert first["ext"] == {"work": "BWV 1"}

    second = data["tracks"][1]
    assert second["audio_fingerprint"] is None
    assert second["cover_hash"] is None

    encoded = response.text
    assert "stream_url" not in encoded
    assert "download_url" not in encoded
    assert "cover_url" not in encoded


@pytest.mark.asyncio
async def test_export_empty_playlist(client):
    db = SessionLocal()
    try:
        playlist = models.Playlist(name="Empty Export", art_color="art-1")
        db.add(playlist)
        db.commit()
        playlist_id = playlist.id
    finally:
        db.close()

    response = await client.get("/rest/exportPlaylist", params={"id": playlist_id})

    assert response.status_code == 200
    data = response.json()
    assert data["playlist"]["track_count"] == 0
    assert data["tracks"] == []


@pytest.mark.asyncio
async def test_export_playlist_not_found(client):
    response = await client.get("/rest/exportPlaylist", params={"id": 9999})
    assert response.status_code == 404
    assert response.json()["detail"] == "歌单不存在"


def test_cover_hash_from_legacy_cover_file(monkeypatch, tmp_path):
    cover = tmp_path / "legacy-cover.jpg"
    cover.write_bytes(b"legacy-cover")
    expected = hashlib.sha256(b"legacy-cover").hexdigest()
    monkeypatch.setattr(rest, "_cover_file_from_path", lambda _path: cover)

    assert rest._cover_hash_from_path("legacy-cover.jpg") == expected
