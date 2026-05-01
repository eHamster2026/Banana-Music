import pytest


async def _register(client, username: str, email: str) -> str:
    r = await client.post(
        "/auth/register",
        json={"username": username, "email": email, "password": "secret123"},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.mark.asyncio
async def test_create_playlist_rejects_duplicate_name(client):
    token = await _register(client, "pluser1", "pl1@example.com")
    h = {"Authorization": f"Bearer {token}"}
    r1 = await client.post(
        "/playlists",
        json={"name": "我的歌单", "art_color": "art-1"},
        headers=h,
    )
    assert r1.status_code == 200
    r2 = await client.post(
        "/playlists",
        json={"name": "我的歌单", "art_color": "art-2"},
        headers=h,
    )
    assert r2.status_code == 409
    assert r2.json()["detail"] == "已存在同名歌单"


@pytest.mark.asyncio
async def test_create_playlist_duplicate_case_insensitive(client):
    token = await _register(client, "pluser2", "pl2@example.com")
    h = {"Authorization": f"Bearer {token}"}
    await client.post(
        "/playlists",
        json={"name": "Rock", "art_color": "art-1"},
        headers=h,
    )
    r = await client.post(
        "/playlists",
        json={"name": "rock", "art_color": "art-2"},
        headers=h,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_different_users_may_use_same_playlist_name(client):
    t1 = await _register(client, "pluser3a", "pl3a@example.com")
    t2 = await _register(client, "pluser3b", "pl3b@example.com")
    r1 = await client.post(
        "/playlists",
        json={"name": "共享名", "art_color": "art-1"},
        headers={"Authorization": f"Bearer {t1}"},
    )
    r2 = await client.post(
        "/playlists",
        json={"name": "共享名", "art_color": "art-2"},
        headers={"Authorization": f"Bearer {t2}"},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_update_playlist_rejects_duplicate_name(client):
    token = await _register(client, "pluser4", "pl4@example.com")
    h = {"Authorization": f"Bearer {token}"}
    a = await client.post(
        "/playlists",
        json={"name": "列表 A", "art_color": "art-1"},
        headers=h,
    )
    b = await client.post(
        "/playlists",
        json={"name": "列表 B", "art_color": "art-2"},
        headers=h,
    )
    assert a.status_code == 200 and b.status_code == 200
    bid = b.json()["id"]
    r = await client.put(
        f"/playlists/{bid}",
        json={"name": "列表 A"},
        headers=h,
    )
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_update_playlist_same_name_ok(client):
    token = await _register(client, "pluser5", "pl5@example.com")
    h = {"Authorization": f"Bearer {token}"}
    a = await client.post(
        "/playlists",
        json={"name": "仅一个", "art_color": "art-1"},
        headers=h,
    )
    assert a.status_code == 200
    pid = a.json()["id"]
    r = await client.put(
        f"/playlists/{pid}",
        json={"name": "仅一个", "description": "改描述"},
        headers=h,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "仅一个"
