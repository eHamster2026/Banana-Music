"""track_metadata_update：diff、JSONL 追加、统一写入口。"""
import json

import pytest

from services import track_metadata_update as tmu


def test_diff_metadata_detects_changes():
    before = {"title": "a", "artist_name": "x", "album_id": 1}
    after = {"title": "b", "artist_name": "x", "album_id": 1}
    d = tmu.diff_metadata(before, after)
    assert set(d.keys()) == {"title"}
    assert d["title"]["before"] == "a"
    assert d["title"]["after"] == "b"


def test_log_appends_jsonl(monkeypatch, tmp_path):
    log_file = tmp_path / "metadata_changes.jsonl"
    monkeypatch.setattr(tmu, "_log_path_fn", lambda: log_file)
    monkeypatch.setattr(tmu.settings, "banana_testing", False)

    tmu.log_metadata_change(
        source="unit_test",
        track_id=42,
        changes={"title": {"before": "a", "after": "b"}},
        extra={"k": "v"},
    )
    text = log_file.read_text(encoding="utf-8")
    row = json.loads(text.strip())
    assert row["source"] == "unit_test"
    assert row["track_id"] == 42
    assert row["changes"]["title"]["after"] == "b"
    assert row["extra"]["k"] == "v"


def test_log_skipped_when_banana_testing(monkeypatch, tmp_path):
    log_file = tmp_path / "metadata_changes.jsonl"
    monkeypatch.setattr(tmu, "_log_path_fn", lambda: log_file)
    monkeypatch.setattr(tmu.settings, "banana_testing", True)

    tmu.log_metadata_change(
        source="x",
        track_id=1,
        changes={"title": {"before": "a", "after": "b"}},
    )
    assert not log_file.exists()
