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
from bulk_import_utils import MetadataResult


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

    async def fake_upload_file_with_client(client, upload_path, **kwargs):
        captured["path"] = upload_path
        captured["metadata"] = kwargs["metadata"]
        captured["parse_metadata"] = kwargs["parse_metadata"]
        return {"file": str(upload_path), "status": "added", "track_id": 1}

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(upload_audio_dir.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(upload_audio_dir, "read_embedded_metadata", fake_read_embedded_metadata)
    monkeypatch.setattr(upload_audio_dir, "upload_file_with_client", fake_upload_file_with_client)

    queue = asyncio.Queue()
    queue.put_nowait((1, path))
    queue.put_nowait(None)
    results = [None]
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
        total=1,
        client=object(),
        args=args,
    )

    assert captured["path"] == path
    assert captured["parse_metadata"] is False
    assert captured["metadata"].title == "Cantata"
    assert captured["metadata"].artists == ["Bach"]
    assert results == [{"file": str(path), "status": "added", "track_id": 1}]
