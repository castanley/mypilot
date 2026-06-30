"""Admin authorization boundary: a non-admin authenticated user (is_admin=False) must be FORBIDDEN
from every admin surface. They can manage their own devices/routes (covered by test_owner_scoping);
they must NOT reach the admin audit log, fork/stack config, deployment health, dev tools, or the
retention setting. The gate is pinned directly on the `is_admin` flag so it holds regardless of how a
user was created.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient, Cookies

from .helpers import setup_admin


async def _make_non_admin_client(app) -> tuple[AsyncClient, str]:
    """Create a non-admin user directly + return a logged-in client + CSRF."""
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password

    async with SessionLocal() as db:
        db.add(User(username="plainuser", password_hash=hash_password("plain-pass-123"), is_admin=False))
        await db.commit()

    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=Cookies())
    r = await c.post("/api/auth/login", json={"username": "plainuser", "password": "plain-pass-123"})
    assert r.status_code == 200, r.text
    return c, r.json()["csrf_token"]


# (method, path, needs_csrf) for every platform-admin endpoint a non-admin must be denied.
_ADMIN_GETS = [
    "/api/admin/health",
    "/api/admin/audit",
    "/api/admin/config",
    "/api/retention",
]


async def test_non_admin_forbidden_on_admin_reads(app):
    await setup_admin(AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=Cookies()))
    cu, _ = await _make_non_admin_client(app)
    for path in _ADMIN_GETS:
        r = await cu.get(path)
        assert r.status_code == 403, f"{path} must be 403 for a non-admin, got {r.status_code}"
    await cu.aclose()


async def test_non_admin_forbidden_on_admin_writes(app):
    await setup_admin(AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=Cookies()))
    cu, csrf = await _make_non_admin_client(app)
    h = {"X-CSRF-Token": csrf}
    # fork/stack config patch
    r = await cu.patch("/api/admin/config", json={"stack_url": "http://evil"}, headers=h)
    assert r.status_code == 403, f"PATCH /api/admin/config got {r.status_code}"
    # global retention (full-replace)
    r = await cu.put("/api/retention", json={"days": 0, "route_days": 1, "log_days": 1}, headers=h)
    assert r.status_code == 403, f"PUT /api/retention got {r.status_code}"
    # dev tools: create a sim device
    r = await cu.post("/api/admin/dev/sim-devices", json={"alias": "x"}, headers=h)
    assert r.status_code == 403, f"POST /api/admin/dev/sim-devices got {r.status_code}"
    await cu.aclose()


async def test_public_health_has_no_usage_stats(app):
    """The unauthenticated /api/health liveness probe must NOT leak deployment-wide usage (device/route
    counts, DB/object-store sizes). A logged-OUT client gets only
    component ok/down."""
    anon = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=Cookies())
    r = await anon.get("/api/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ok" in body and "components" in body
    for name, comp in body["components"].items():
        assert comp.get("usage") is None, f"/api/health leaked usage for {name}: {comp.get('usage')}"
    await anon.aclose()


async def test_admin_health_includes_usage(app):
    """The admin-gated /api/admin/health DOES include the rich usage stats (so the operator's
    dashboard still works)."""
    ca = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=Cookies())
    await setup_admin(ca)
    r = await ca.get("/api/admin/health")
    assert r.status_code == 200, r.text
    # In the test profile the DB is sqlite + storage is in-memory, but the device/route counts come
    # back regardless (>=0), proving the usage payload is populated for admins.
    db = r.json()["components"].get("database", {})
    assert db.get("usage") is not None and "devices" in db["usage"]
    await ca.aclose()


async def test_admin_still_allowed(app):
    """Sanity: the global admin (is_admin=True) still reaches the admin surface — the gate denies
    non-admins, not everyone."""
    ca = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=Cookies())
    await setup_admin(ca)
    for path in _ADMIN_GETS:
        r = await ca.get(path)
        assert r.status_code == 200, f"admin {path} got {r.status_code}"
    await ca.aclose()
