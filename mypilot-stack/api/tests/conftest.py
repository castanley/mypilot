"""Test fixtures: a fresh SQLite schema + fakeredis per test, served via httpx ASGITransport."""

from __future__ import annotations

import os
import tempfile

# Configure the environment BEFORE importing the app (settings are cached at import time).
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMP_DB.close()
os.environ.setdefault("MYPILOT_ENV", "test")
os.environ.setdefault("API_SECRET_KEY", "test-secret-key")
# Force non-Secure cookies for the test client: it talks to the app over http://test, and httpx
# (correctly) won't resend a Secure cookie over plain HTTP — which would 401 every authenticated
# request. The deployed container may set COOKIE_SECURE=1, so override it here, not via setdefault.
os.environ["COOKIE_SECURE"] = "0"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.name}"

import fakeredis.aioredis  # noqa: E402
import pytest_asyncio  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.realtime import ConnectionManager  # noqa: E402
from httpx import ASGITransport, AsyncClient, Cookies  # noqa: E402


@pytest_asyncio.fixture
async def app():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    application = create_app()
    application.state.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    application.state.manager = ConnectionManager()

    from app.db import SessionLocal  # noqa: E402
    from app.seed import seed_models, seed_releases, seed_settings  # noqa: E402

    async with SessionLocal() as session:
        await seed_settings(session)
        await seed_models(session)
        await seed_releases(session)

    try:
        yield application
    finally:
        await application.state.redis.aclose()


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    # httpx >= 0.28 no longer persists Set-Cookie across requests on an ASGITransport client unless a
    # cookie jar is attached. The auth flow is cookie-based (session + csrf), so without this the
    # client drops the login cookie and every authenticated request 401s. Attach an explicit jar.
    async with AsyncClient(transport=transport, base_url="http://test", cookies=Cookies()) as c:
        yield c
