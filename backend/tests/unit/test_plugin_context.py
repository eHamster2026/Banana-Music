from pathlib import Path

import models
from database import SessionLocal
from plugins.base import TrackMeta
from plugins.context import PluginContext


def test_ingest_file_uses_current_upload_helpers(monkeypatch, tmp_path: Path):
    import routers.upload as upload

    resource_dir = tmp_path / "resource"
    monkeypatch.setattr(upload, "RESOURCE_DIR", resource_dir)
    monkeypatch.setattr(
        upload,
        "_process_uploaded_file_sync",
        lambda _path, _name: {
            "audio_hash": b"plugin-ingest-01",
            "duration": 123,
            "final_suffix": ".mp3",
        },
    )
    monkeypatch.setattr(upload, "enqueue_fingerprint_task", lambda _db, _track_id: None)

    source = tmp_path / "downloaded.mp3"
    source.write_bytes(b"fake audio")

    ctx = PluginContext("test-plugin", {})
    result = ctx.ingest_file(
        source,
        TrackMeta(
            title="Downloaded Title",
            artist="Downloaded Artist",
            album="Downloaded Album",
            track_number=7,
        ),
    )

    assert result["status"] == "added"

    db = SessionLocal()
    try:
        track = db.get(models.Track, result["track_id"])
        assert track is not None
        assert track.title == "Downloaded Title"
        assert track.is_local is True
        assert track.stream_url.startswith("/resource/")
        assert track.album.title == "Downloaded Album"
        assert track.artist.name == "Downloaded Artist"
    finally:
        db.close()
