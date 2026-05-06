import time

import pytest

from routers import upload
from routers.upload import _parse_filename, _parse_track_number
from services.artist_names import artist_names_from_tag_dict


def test_parse_filename_track_title_artist():
    assert _parse_filename("01. Title — Artist") == (1, "Title", "Artist")
    assert _parse_filename("12. 歌名 - 艺人") == (12, "歌名", "艺人")


def test_parse_filename_no_match():
    assert _parse_filename("no pattern here") is None


def test_parse_track_number():
    assert _parse_track_number("3") == 3
    assert _parse_track_number("3/10") == 3
    assert _parse_track_number("") == 0


def test_artist_names_from_tag_dict_preserves_tag_artist_list():
    assert artist_names_from_tag_dict({"artists": ["陶喆", "A-Lin", "陶喆"]}) == ["陶喆", "A-Lin"]


@pytest.mark.asyncio
async def test_parse_tags_for_create_times_out(monkeypatch, tmp_path):
    monkeypatch.setattr(upload.settings, "banana_testing", False)
    monkeypatch.setattr(upload, "_METADATA_PARSE_TIMEOUT_SEC", 0.01)

    def slow_parse(_path):
        time.sleep(0.1)
        return {"title": "Late Title", "artist": "Late Artist"}

    monkeypatch.setattr(upload, "_parse_tags", slow_parse)

    assert await upload._parse_tags_for_create(tmp_path / "slow.flac") == {}
