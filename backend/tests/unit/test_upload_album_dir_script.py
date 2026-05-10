import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import upload_album_dir
from bulk_import_utils import MetadataResult


def test_album_tracks_with_track_numbers_keeps_discovery_order(monkeypatch, tmp_path):
    first_seen = tmp_path / "b.flac"
    second_seen = tmp_path / "a.flac"
    first_seen.write_bytes(b"fake")
    second_seen.write_bytes(b"fake")

    numbers = {
        first_seen: 2,
        second_seen: 1,
    }

    def fake_read_embedded_metadata(path, *, timeout):
        return MetadataResult(track_number=numbers[path])

    monkeypatch.setattr(upload_album_dir, "read_embedded_metadata", fake_read_embedded_metadata)

    assert upload_album_dir.album_tracks_with_track_numbers([first_seen, second_seen], metadata_timeout=5.0) == [
        (first_seen, 2),
        (second_seen, 1),
    ]


def test_album_tracks_with_track_numbers_submits_none_when_missing(monkeypatch, tmp_path):
    first_seen = tmp_path / "b.flac"
    second_seen = tmp_path / "a.flac"
    first_seen.write_bytes(b"fake")
    second_seen.write_bytes(b"fake")

    def fake_read_embedded_metadata(path, *, timeout):
        if path == first_seen:
            return MetadataResult(track_number=2)
        return MetadataResult(track_number=None)

    monkeypatch.setattr(upload_album_dir, "read_embedded_metadata", fake_read_embedded_metadata)

    assert upload_album_dir.album_tracks_with_track_numbers([first_seen, second_seen], metadata_timeout=5.0) == [
        (first_seen, 2),
        (second_seen, None),
    ]
