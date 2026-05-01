import pytest


@pytest.mark.asyncio
async def test_search_returns_empty_lists(client):
    r = await client.get("/search?q=x")
    assert r.status_code == 200
    data = r.json()
    assert data["tracks"] == []
    assert data["albums"] == []
    assert data["artists"] == []
    assert data["playlists"] == []
    assert data.get("plugin_hits") == []


@pytest.mark.asyncio
async def test_suggestions_empty_db(client):
    r = await client.get("/search/suggestions?q=a")
    assert r.status_code == 200
    assert r.json()["suggestions"] == []
