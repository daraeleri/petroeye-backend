"""Test setup: SQLite (aiosqlite) in a temp file, no MQTT broker.

Environment is set BEFORE importing the app, because the engine and
settings are created at import time.
"""
import os
import tempfile
from pathlib import Path

_DB_FILE = Path(tempfile.mkdtemp(prefix="petrotwin-test-")) / "test.db"
os.environ.update({
    "DATABASE_URL": f"sqlite+aiosqlite:///{_DB_FILE.as_posix()}",
    "MQTT_ENABLED": "false",
    "ADMIN_EMAIL": "admin@example.com",
    "ADMIN_PASSWORD": "admin-pass-123",
    "JWT_SECRET": "test-secret-not-for-production-use-0123456789",
    "AUTO_REGISTER_TRUCKS": "true",
})

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.db import models  # noqa: E402,F401
from app.db.base import AsyncSessionLocal, Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.bootstrap import ensure_admin  # noqa: E402

ADMIN = ("admin@example.com", "admin-pass-123")


@pytest.fixture(scope="session", autouse=True)
async def _schema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_admin()
    yield
    await engine.dispose()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def login(client: httpx.AsyncClient, email: str, password: str) -> dict[str, str]:
    r = await client.post("/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def admin_headers(client):
    return await login(client, *ADMIN)


@pytest.fixture
async def session():
    async with AsyncSessionLocal() as s:
        yield s
