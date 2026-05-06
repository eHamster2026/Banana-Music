import pytest

import models
from database import SessionLocal
from routers import upload


def _stage_upload(file_key: str, tmp_path):
    staged_file = tmp_path / file_key
    staged_file.write_bytes(b"fake audio")

    db = SessionLocal()
    try:
        db.add(
            models.UploadStaging(
                file_key=file_key,
                audio_hash=(b"audio-hash-" + file_key[:4].encode("ascii")).ljust(16, b"-"),
                original_name="Artist - Title.flac",
                duration_sec=123,
            )
        )
        db.commit()
    finally:
        db.close()


def _parse_task_count() -> int:
    db = SessionLocal()
    try:
        return db.query(models.ParseUploadTask).count()
    finally:
        db.close()


def _create_track_with_hash(audio_hash: bytes, title: str = "Existing Title") -> int:
    db = SessionLocal()
    try:
        artist = models.Artist(
            name="Existing Artist",
            art_color="art-1",
            bio="",
            monthly_listeners=0,
        )
        db.add(artist)
        db.flush()
        track = models.Track(
            title=title,
            artist_id=artist.id,
            duration_sec=123,
            stream_url="/resource/existing.flac",
            audio_hash=audio_hash,
        )
        db.add(track)
        db.commit()
        return track.id
    finally:
        db.close()


@pytest.mark.asyncio
async def test_exists_by_hash_is_anonymous_and_returns_track(client):
    audio_hash = bytes.fromhex("00112233445566778899aabbccddeeff")
    track_id = _create_track_with_hash(audio_hash)

    r = await client.get(
        "/rest/x-banana/tracks/exists-by-hash",
        params={"audio_hash": audio_hash.hex()},
    )

    assert r.status_code == 200
    assert r.json() == {
        "exists": True,
        "track_id": track_id,
        "title": "Existing Title",
    }


@pytest.mark.asyncio
async def test_exists_by_hash_returns_false_for_missing_hash(client):
    r = await client.get(
        "/rest/x-banana/tracks/exists-by-hash",
        params={"audio_hash": "ffeeddccbbaa99887766554433221100"},
    )

    assert r.status_code == 200
    assert r.json() == {"exists": False, "track_id": None, "title": None}


@pytest.mark.asyncio
async def test_exists_by_hash_rejects_invalid_hash(client):
    r = await client.get(
        "/rest/x-banana/tracks/exists-by-hash",
        params={"audio_hash": "not-a-hash"},
    )

    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_track_parse_metadata_false_skips_parse_upload_task(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(upload, "RESOURCE_DIR", tmp_path)
    monkeypatch.setattr(
        upload, "_parse_tags", lambda _path: {"title": "Title", "artist": "Artist"}
    )
    file_key = "a" * 64 + ".flac"
    _stage_upload(file_key, tmp_path)

    r = await client.post(
        "/rest/x-banana/tracks/create",
        json={"file_key": file_key, "parse_metadata": False},
    )

    assert r.status_code == 200
    assert r.json()["status"] == "added"
    assert _parse_task_count() == 0


@pytest.mark.asyncio
async def test_create_track_parse_metadata_defaults_to_true(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(upload, "RESOURCE_DIR", tmp_path)
    monkeypatch.setattr(
        upload, "_parse_tags", lambda _path: {"title": "Title", "artist": "Artist"}
    )
    file_key = "b" * 64 + ".flac"
    _stage_upload(file_key, tmp_path)

    r = await client.post("/rest/x-banana/tracks/create", json={"file_key": file_key})

    assert r.status_code == 200
    assert r.json()["status"] == "added"
    assert _parse_task_count() == 1


@pytest.mark.asyncio
async def test_create_track_metadata_override_takes_precedence(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(upload, "RESOURCE_DIR", tmp_path)
    monkeypatch.setattr(
        upload,
        "_parse_tags",
        lambda _path: {"title": "Raw Title", "artist": "Raw Artist"},
    )
    file_key = "c" * 64 + ".mp3"
    _stage_upload(file_key, tmp_path)

    r = await client.post(
        "/rest/x-banana/tracks/create",
        json={
            "file_key": file_key,
            "parse_metadata": False,
            "metadata": {
                "title": "Clean Title",
                "artists": ["Clean Artist", "Guest Artist"],
                "album": "Clean Album",
                "track_number": 7,
            },
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "added"
    assert body["title"] == "Clean Title"
    assert body["artists"] == ["Clean Artist", "Guest Artist"]

    db = SessionLocal()
    try:
        track = db.get(models.Track, body["track_id"])
        assert track.title == "Clean Title"
        assert track.artist.name == "Clean Artist"
        assert track.album.title == "Clean Album"
        assert track.track_number == 7
        assert [ta.artist.name for ta in track.track_artists] == ["Guest Artist"]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_create_track_metadata_override_survives_tag_parse_failure(
    client, monkeypatch, tmp_path
):
    monkeypatch.setattr(upload, "RESOURCE_DIR", tmp_path)

    def fail_parse(_path):
        raise RuntimeError("parser unavailable")

    monkeypatch.setattr(upload, "_parse_tags", fail_parse)
    file_key = "d" * 64 + ".mp3"
    _stage_upload(file_key, tmp_path)

    r = await client.post(
        "/rest/x-banana/tracks/create",
        json={
            "file_key": file_key,
            "parse_metadata": False,
            "metadata": {
                "title": "Client Title",
                "artists": ["Client Artist"],
            },
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "added"
    assert body["title"] == "Client Title"
    assert body["artists"] == ["Client Artist"]
