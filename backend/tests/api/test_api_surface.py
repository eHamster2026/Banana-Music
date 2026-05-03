import pytest

from main import app


def _registered_routes():
    routes = set()
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        for method in methods - {"HEAD", "OPTIONS"}:
            routes.add((method, path))
    return routes


@pytest.mark.asyncio
async def test_duplicate_x_banana_routes_are_not_registered(client):
    routes = _registered_routes()

    assert ("GET", "/rest/search3") in routes
    assert ("GET", "/rest/getPlayQueue") in routes
    assert ("POST", "/rest/x-banana/queue/command") in routes

    assert ("GET", "/rest/x-banana/search") not in routes
    assert ("GET", "/rest/x-banana/search/suggestions") not in routes
    assert ("GET", "/rest/x-banana/queue") not in routes
    assert ("GET", "/rest/x-banana/queue/events") not in routes

    removed = await client.get("/rest/x-banana/search/suggestions?q=a")
    assert removed.status_code == 404
