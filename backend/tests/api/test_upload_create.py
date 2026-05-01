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
                audio_hash=b"audio-hash-" + file_key[:4].encode("ascii"),
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
        "/tracks/create", json={"file_key": file_key, "parse_metadata": False}
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

    r = await client.post("/tracks/create", json={"file_key": file_key})

    assert r.status_code == 200
    assert r.json()["status"] == "added"
    assert _parse_task_count() == 1
