"""Authorization guard: a user only ever sees and touches the devices they own.

Every device router (devices/routes/settings/backups/software) decides access through
`ownership.owns_device`. This test asserts that holds end-to-end across those endpoints, so a missed
call site turns into a RED build rather than a quiet data leak.

User A sets up, pairs a device, and creates a route + a backup. A second user logs in on a fresh
client and must get 404 on every one of A's resources (404, not 403 — we don't reveal existence)."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient, Cookies

from .helpers import device_post, device_put, pair_device, setup_admin

HEARTBEAT = "/api/devices/self/heartbeat"


async def _make_second_user_client(app) -> tuple[AsyncClient, str]:
    """Create a second user directly in the DB and return a logged-in client + CSRF."""
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password

    async with SessionLocal() as db:
        db.add(User(username="userb", password_hash=hash_password("userb-pass-123"), is_admin=True))
        await db.commit()

    transport = ASGITransport(app=app)
    cb = AsyncClient(transport=transport, base_url="http://test", cookies=Cookies())
    r = await cb.post("/api/auth/login", json={"username": "userb", "password": "userb-pass-123"})
    assert r.status_code == 200, r.text
    return cb, r.json()["csrf_token"]


async def _seed_user_a(client) -> dict:
    """Set up user A, pair a device, create a route + a backup. Returns the ids B must not reach."""
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)

    # A route with an actually-uploaded file, so the blob-serving paths (download/stream/playlist)
    # have a real file_id + stored bytes to probe — these serve raw video/qlog and are the highest
    # cross-account leak risk, so they must be in the isolation guard.
    start = await device_post(
        client, device_id, keys, "/api/ingest/routes/start",
        {"name": "2026-06-28--09-00-00", "segment_count": 1,
         "files": [{"segment_index": 0, "name": "qlog.zst", "kind": "qlog"}]},
    )
    assert start.status_code == 201, start.text
    route_id = start.json()["route_id"]
    put = await device_put(
        client, device_id, keys, f"/api/ingest/routes/{route_id}/files/0/qlog.zst", b"SECRET-BYTES" * 8
    )
    assert put.status_code == 200, put.text
    await device_post(client, device_id, keys, f"/api/ingest/routes/{route_id}/complete", {})
    # Grab the file_id from the (owner's) route detail.
    detail = (await client.get(f"/api/routes/{route_id}")).json()
    file_id = detail["files"][0]["id"]

    # A backup (needs an onroad=false heartbeat first so the device has settings state).
    await device_post(client, device_id, keys, HEARTBEAT, {"onroad": False})
    b = await client.post(
        f"/api/devices/{device_id}/backups", json={"name": "snap1"}, headers={"X-CSRF-Token": csrf}
    )
    assert b.status_code == 201, b.text
    backup_id = b.json()["id"]
    return {"device_id": device_id, "route_id": route_id, "file_id": file_id,
            "backup_id": backup_id, "csrf": csrf}


async def test_user_b_cannot_reach_user_a_resources(app, client):
    ids = await _seed_user_a(client)
    cb, csrf_b = await _make_second_user_client(app)
    try:
        d, r, bk, fid = ids["device_id"], ids["route_id"], ids["backup_id"], ids["file_id"]

        # B's own world is empty — proves B is a real, separate account.
        assert (await cb.get("/api/devices")).json() == []

        # Every owner-scoped READ of A's resources must 404 for B — INCLUDING the blob-serving paths
        # (download/stream/playlist) that hand back raw video/qlog bytes + the audit trail. These are
        # the highest cross-account leak risk, so a future endpoint that forgets the owner check fails
        # this test instead of silently leaking another user's dashcam footage / location.
        gets = [
            f"/api/devices/{d}",
            f"/api/devices/{d}/status",
            f"/api/devices/{d}/settings",
            f"/api/devices/{d}/software",
            f"/api/devices/{d}/routes",
            f"/api/devices/{d}/logs",
            f"/api/devices/{d}/audit",
            f"/api/devices/{d}/backups/{bk}/diff",
            f"/api/routes/{r}",
            f"/api/routes/{r}/track",
            f"/api/routes/{r}/playlist.m3u8",
            f"/api/routes/{r}/files/{fid}/download",
            f"/api/routes/{r}/files/{fid}/stream",
            f"/api/backups/{bk}",
            f"/api/backups/{bk}/download",
        ]
        for path in gets:
            resp = await cb.get(path)
            assert resp.status_code == 404, f"LEAK: B read {path} -> {resp.status_code} (expected 404)"

        # Owner-scoped MUTATIONS of A's resources must also 404 (CSRF-protected; send B's token).
        h = {"X-CSRF-Token": csrf_b}
        assert (await cb.patch(f"/api/devices/{d}", json={"alias": "hijack"}, headers=h)).status_code == 404
        assert (await cb.delete(f"/api/devices/{d}", headers=h)).status_code == 404
        assert (await cb.delete(f"/api/routes/{r}", headers=h)).status_code == 404
        assert (await cb.delete(f"/api/backups/{bk}", headers=h)).status_code == 404

        # And A's device + route are untouched (the failed mutations didn't leak through).
        assert (await client.get(f"/api/devices/{d}")).json()["alias"] != "hijack"
    finally:
        await cb.aclose()
