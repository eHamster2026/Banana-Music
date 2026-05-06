import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import bulk_import_utils
import upload_audio_dir
from bulk_import_utils import EmbeddedCover, MetadataResult


def test_read_embedded_metadata_reads_ffprobe_tags(monkeypatch, tmp_path):
    path = tmp_path / "sample.flac"
    path.write_bytes(b"fake")

    def fake_run(*args, **kwargs):
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout=json.dumps(
                {
                    "format": {
                        "tags": {
                            "ARTIST": "Bach",
                            "TITLE": "Cantata",
                            "ALBUM": "Bach 2000",
                            "TRACKNUMBER": "12/20",
                        }
                    },
                    "streams": [],
                }
            ),
        )

    monkeypatch.setattr(bulk_import_utils.subprocess, "run", fake_run)

    metadata = bulk_import_utils.read_embedded_metadata(path)

    assert metadata.title == "Cantata"
    assert metadata.artists == ["Bach"]
    assert metadata.album == "Bach 2000"
    assert metadata.track_number == 12


@pytest.mark.asyncio
async def test_upload_worker_sends_extracted_metadata(monkeypatch, tmp_path):
    path = tmp_path / "sample.flac"
    path.write_bytes(b"fake")
    captured = {}

    def fake_read_embedded_metadata(_path, *, timeout):
        return MetadataResult(title="Cantata", artists=["Bach"], album="Bach 2000", track_number=12)

    def fake_read_embedded_cover(_path):
        return EmbeddedCover(data=b"cover", ext=".jpg")

    async def fake_upload_file_with_client(client, upload_path, **kwargs):
        captured["path"] = upload_path
        captured["metadata"] = kwargs["metadata"]
        captured["cover"] = kwargs["cover"]
        captured["parse_metadata"] = kwargs["parse_metadata"]
        return {"file": str(upload_path), "status": "added", "track_id": 1}

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(upload_audio_dir.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(upload_audio_dir, "read_embedded_metadata", fake_read_embedded_metadata)
    monkeypatch.setattr(upload_audio_dir, "read_embedded_cover", fake_read_embedded_cover)
    monkeypatch.setattr(upload_audio_dir, "upload_file_with_client", fake_upload_file_with_client)

    queue = asyncio.Queue()
    queue.put_nowait((1, 1, path))
    queue.put_nowait(None)
    results = [None]
    graceful_stop_event = asyncio.Event()
    args = argparse.Namespace(
        metadata_check_timeout=5.0,
        base_url="http://test",
        poll_interval=0.1,
        job_timeout=1.0,
        verbose=False,
    )

    await upload_audio_dir.upload_worker(
        worker_id=1,
        queue=queue,
        results=results,
        total_state={"seen": 1, "final": 1},
        client=object(),
        args=args,
        graceful_stop_event=graceful_stop_event,
    )

    assert captured["path"] == path
    assert captured["parse_metadata"] is False
    assert captured["metadata"].title == "Cantata"
    assert captured["metadata"].artists == ["Bach"]
    assert captured["cover"].data == b"cover"
    assert results == [{"file": str(path), "status": "added", "track_id": 1}]


@pytest.mark.asyncio
async def test_upload_file_with_client_uploads_cover_before_create(tmp_path):
    path = tmp_path / "sample.flac"
    path.write_bytes(b"fake")

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class FakeClient:
        def __init__(self):
            self.posts = []
            self.status_calls = 0

        async def post(self, url, **kwargs):
            self.posts.append((url, kwargs))
            if url.endswith("/upload-file"):
                return FakeResponse({"job_id": "job-1"})
            if url.endswith("/covers/upload"):
                return FakeResponse({"cover_id": "abc123.jpg"})
            if url.endswith("/create"):
                return FakeResponse({"status": "added", "track_id": 7})
            raise AssertionError(f"unexpected post: {url}")

        async def get(self, url):
            self.status_calls += 1
            return FakeResponse({"state": "done", "status": "ok", "file_key": "sample.flac"})

    client = FakeClient()
    result = await bulk_import_utils.upload_file_with_client(
        client,
        path,
        base_url="http://test",
        parse_metadata=False,
        metadata=MetadataResult(title="Cantata", artists=["Bach"]),
        cover=EmbeddedCover(data=b"\xff\xd8\xffcover", ext=".jpg"),
        poll_interval=0,
        job_timeout=1,
    )

    create_url, create_kwargs = client.posts[-1]
    assert create_url.endswith("/rest/x-banana/tracks/create")
    assert create_kwargs["json"]["cover_id"] == "abc123.jpg"
    assert result == {"file": str(path), "status": "added", "track_id": 7}
