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
    queue.put_nowait((1, 1, path))
    queue.put_nowait(None)
    results = [None]
    total_state = {"seen": 1, "final": 1}
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
        total_state=total_state,
        client=object(),
        args=args,
        graceful_stop_event=asyncio.Event(),
    )

    assert captured["path"] == path
    assert captured["parse_metadata"] is False
    assert captured["metadata"].title == "Cantata"
    assert captured["metadata"].artists == ["Bach"]
    assert results == [{"file": str(path), "status": "added", "track_id": 1}]


def _upload_dir_args(tmp_path):
    return argparse.Namespace(
        directory=tmp_path,
        no_recursive=False,
        concurrency=1,
        max_connections=0,
        metadata_check_timeout=5.0,
        poll_interval=0.1,
        job_timeout=1.0,
        request_timeout=1.0,
        base_url="http://test",
        api_key="am_test",
        token=None,
        username=None,
        password=None,
        verbose=False,
    )


@pytest.mark.asyncio
async def test_run_first_stop_waits_for_current_worker(monkeypatch, tmp_path):
    path = tmp_path / "sample.flac"
    path.write_bytes(b"fake")

    async def fake_resolve_upload_token(_args):
        return None

    def fake_install_stop_handlers():
        graceful = asyncio.Event()
        force = asyncio.Event()
        asyncio.get_running_loop().call_soon(graceful.set)
        return graceful, force

    def fake_read_embedded_metadata(_path, *, timeout):
        return MetadataResult(title="Cantata", artists=["Bach"])

    async def fake_upload_file_with_client(*args, **kwargs):
        await asyncio.sleep(0)
        return {"status": "added", "track_id": 1}

    monkeypatch.setattr(upload_audio_dir, "resolve_upload_token", fake_resolve_upload_token)
    monkeypatch.setattr(upload_audio_dir, "_install_stop_handlers", fake_install_stop_handlers)
    monkeypatch.setattr(upload_audio_dir, "read_embedded_metadata", fake_read_embedded_metadata)
    monkeypatch.setattr(upload_audio_dir, "upload_file_with_client", fake_upload_file_with_client)

    await asyncio.wait_for(upload_audio_dir.run(_upload_dir_args(tmp_path)), timeout=1)


@pytest.mark.asyncio
async def test_run_second_stop_cancels_workers(monkeypatch, tmp_path):
    path = tmp_path / "sample.flac"
    path.write_bytes(b"fake")

    async def fake_resolve_upload_token(_args):
        return None

    def fake_install_stop_handlers():
        graceful = asyncio.Event()
        force = asyncio.Event()
        loop = asyncio.get_running_loop()
        loop.call_soon(graceful.set)
        loop.call_later(0.01, force.set)
        return graceful, force

    def fake_read_embedded_metadata(_path, *, timeout):
        return MetadataResult(title="Cantata", artists=["Bach"])

    async def fake_upload_file_with_client(*args, **kwargs):
        await asyncio.sleep(10)
        return {"status": "added", "track_id": 1}

    monkeypatch.setattr(upload_audio_dir, "resolve_upload_token", fake_resolve_upload_token)
    monkeypatch.setattr(upload_audio_dir, "_install_stop_handlers", fake_install_stop_handlers)
    monkeypatch.setattr(upload_audio_dir, "read_embedded_metadata", fake_read_embedded_metadata)
    monkeypatch.setattr(upload_audio_dir, "upload_file_with_client", fake_upload_file_with_client)

    with pytest.raises(upload_audio_dir.UploadInterrupted):
        await asyncio.wait_for(upload_audio_dir.run(_upload_dir_args(tmp_path)), timeout=1)


@pytest.mark.asyncio
async def test_enqueue_paths_reads_files_on_demand(monkeypatch, tmp_path):
    paths = [tmp_path / "first.flac", tmp_path / "second.flac", tmp_path / "third.flac"]
    for path in paths:
        path.write_bytes(b"fake")
    yielded = []

    def fake_iter_audio_files_lazy(_root, *, recursive):
        for path in paths:
            yielded.append(path)
            yield path

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(upload_audio_dir, "_iter_audio_files_lazy", fake_iter_audio_files_lazy)
    monkeypatch.setattr(upload_audio_dir.asyncio, "to_thread", fake_to_thread)

    queue = asyncio.Queue(maxsize=1)
    results = []
    total_state = {"seen": 0, "final": None}
    graceful_stop = asyncio.Event()
    task = asyncio.create_task(
        upload_audio_dir._enqueue_paths(
            queue,
            tmp_path,
            True,
            1,
            results,
            total_state,
            graceful_stop,
        )
    )

    await asyncio.sleep(0)

    assert yielded == [paths[0]]
    assert results == [None]
    assert total_state["seen"] == 1
    assert queue.get_nowait() == (1, None, paths[0])
    queue.task_done()
    graceful_stop.set()
    await asyncio.sleep(0)
    assert await asyncio.wait_for(queue.get(), timeout=1) is None
    queue.task_done()
    await asyncio.wait_for(task, timeout=1)
    assert yielded == [paths[0]]
