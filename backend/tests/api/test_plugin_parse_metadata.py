from types import SimpleNamespace

import pytest

from auth_utils import create_access_token
import models
from database import SessionLocal
from plugins.base import MetadataPlugin, MetadataResult
from routers import plugins as plugins_router


class _FakeMetadataPlugin(MetadataPlugin):
    async def parse_upload(self, filename_stem, raw_tags=None):
        assert filename_stem == "Artist - Title"
        assert raw_tags["title"] == "Raw"
        return MetadataResult(
            title="Clean",
            artists=["Artist"],
            album="Album",
            confidence=0.9,
        )


@pytest.mark.asyncio
async def test_plugin_specific_parse_metadata_endpoint(client, monkeypatch):
    db = SessionLocal()
    try:
        user = models.User(username="u", email="u@example.com", hashed_password="x")
        db.add(user)
        db.commit()
        token = create_access_token({"sub": str(user.id)})
    finally:
        db.close()

    record = SimpleNamespace(
        enabled=True,
        error=None,
        config={"timeout_sec": 1},
        instance=_FakeMetadataPlugin(),
    )
    monkeypatch.setattr(plugins_router.loader, "get_plugin", lambda plugin_id: record)

    r = await client.post(
        "/rest/x-banana/plugins/llm-metadata/parse-metadata",
        json={"filename_stem": "Artist - Title", "raw_tags": {"title": "Raw"}},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert r.status_code == 200
    assert r.json()["title"] == "Clean"
    assert r.json()["artists"] == ["Artist"]
