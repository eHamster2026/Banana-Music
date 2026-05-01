import pytest

import models
from database import SessionLocal


@pytest.mark.asyncio
async def test_search_returns_empty_lists(client):
    r = await client.get("/rest/search3?query=x")
    assert r.status_code == 200
    data = r.json()
    assert data["tracks"] == []
    assert data["albums"] == []
    assert data["artists"] == []
    assert data["playlists"] == []
    assert data.get("plugin_hits") == []


@pytest.mark.asyncio
async def test_suggestions_empty_db(client):
    r = await client.get("/rest/x-banana/search/suggestions?q=a")
    assert r.status_code == 200
    assert r.json()["suggestions"] == []


@pytest.mark.asyncio
async def test_search_hides_unknown_artist_from_artist_results_and_suggestions(client):
    db = SessionLocal()
    try:
        db.add(models.Artist(name="未知艺人", art_color="art-1"))
        db.commit()
    finally:
        db.close()

    r = await client.get("/rest/search3?query=未知")
    assert r.status_code == 200
    assert r.json()["artists"] == []

    suggestions = await client.get("/rest/x-banana/search/suggestions?q=未知")
    assert suggestions.status_code == 200
    assert suggestions.json()["suggestions"] == []
