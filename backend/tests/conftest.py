"""在导入任何 backend 模块之前开启测试模式（内存库、无 seed、无插件/指纹后台任务）。"""
import os

os.environ["BANANA_TESTING"] = "true"
os.environ.setdefault("FINGERPRINT_ENABLED", "false")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import models
from database import engine
from main import app


@pytest.fixture(autouse=True)
def _reset_db():
    models.Base.metadata.drop_all(bind=engine)
    models.Base.metadata.create_all(bind=engine)
    yield


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
