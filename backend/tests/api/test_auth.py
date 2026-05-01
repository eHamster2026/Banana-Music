import pytest


@pytest.mark.asyncio
async def test_register_login_me(client):
    r = await client.post(
        "/auth/register",
        json={
            "username": "u1",
            "email": "u1@example.com",
            "password": "secret123",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "access_token" in body
    token = body["access_token"]

    me = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me.status_code == 200
    assert me.json()["username"] == "u1"


@pytest.mark.asyncio
async def test_login_invalid_password(client):
    await client.post(
        "/auth/register",
        json={
            "username": "u2",
            "email": "u2@example.com",
            "password": "rightpass",
        },
    )
    r = await client.post(
        "/auth/login",
        json={"username": "u2", "password": "wrong"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_me_without_token(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401
