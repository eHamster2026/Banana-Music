"""Lightweight OpenAPI and auth contract regression tests."""

from __future__ import annotations

import pytest

from main import app


@pytest.mark.asyncio
async def test_search_contract_anonymous_ok(client):
    """/search 可匿名；OpenAPI 可能仍列出可选 Bearer，但无头请求必须 200。"""
    r = await client.get("/search?q=contract")
    assert r.status_code == 200
    data = r.json()
    assert "plugin_hits" in data
    assert isinstance(data["plugin_hits"], list)


def test_openapi_searchresult_includes_plugin_hits():
    """Aggregated search adds plugin_hits when the user is authenticated."""
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    sr = schemas.get("SearchResult")
    assert sr is not None
    props = sr.get("properties", {})
    assert "plugin_hits" in props, "SearchResult should expose plugin_hits for merged search"


def test_openapi_create_track_accepts_parse_metadata_flag():
    """Upload create accepts an opt-out flag for parse_upload metadata cleanup."""
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    req = schemas.get("CreateTrackRequest")
    assert req is not None
    props = req.get("properties", {})
    assert "file_key" in props
    assert "parse_metadata" in props
    assert props["parse_metadata"].get("default") is True
