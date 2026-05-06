"""Lightweight OpenAPI and auth contract regression tests."""

from __future__ import annotations

import pytest

from main import app


@pytest.mark.asyncio
async def test_search_contract_anonymous_ok(client):
    """/rest/search3 可匿名；OpenAPI 可能仍列出可选 Bearer，但无头请求必须 200。"""
    r = await client.get("/rest/search3?query=contract")
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


def test_openapi_create_track_uses_client_metadata_contract():
    """Upload create accepts client metadata and no longer exposes server parse queue flag."""
    spec = app.openapi()
    schemas = spec.get("components", {}).get("schemas", {})
    req = schemas.get("CreateTrackRequest")
    assert req is not None
    props = req.get("properties", {})
    assert "file_key" in props
    assert "metadata" in props
    assert "cover_id" in props
    assert "parse_metadata" not in props
