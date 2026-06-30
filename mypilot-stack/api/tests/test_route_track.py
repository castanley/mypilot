"""Drive-map GPS track: ingest, owner-gated per-drive track + overview, and cross-user isolation."""

from __future__ import annotations

from .helpers import device_post, device_put, pair_device, setup_admin

# [t, lat, lon] — t = seconds since drive start (for video-playback sync).
TRACK = [[0.0, 38.22240, -84.53910], [1.0, 38.22251, -84.53902], [2.0, 38.22260, -84.53888]]


async def _ingest_route_with_track(client, device_id, keys, *, name, track=TRACK):
    start = await device_post(
        client, device_id, keys, "/api/ingest/routes/start",
        {"name": name, "segment_count": 1, "track": track,
         "files": [{"segment_index": 0, "name": "qlog.zst", "kind": "qlog"}]},
    )
    assert start.status_code == 201, start.text
    rid = start.json()["route_id"]
    await device_put(client, device_id, keys, f"/api/ingest/routes/{rid}/files/0/qlog.zst", b"q" * 64)
    await device_post(client, device_id, keys, f"/api/ingest/routes/{rid}/complete", {})
    return rid


async def test_track_ingested_and_served(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    rid = await _ingest_route_with_track(client, device_id, keys, name="2026-06-27--10-00-00")

    # per-drive track endpoint returns the polyline
    r = await client.get(f"/api/routes/{rid}/track")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["route_id"] == rid
    assert body["track"] == TRACK

    # list carries the scalar start point + has_track, but NOT the full array
    lst = (await client.get(f"/api/devices/{device_id}/routes")).json()
    row = next(x for x in lst if x["id"] == rid)
    assert row["has_track"] is True
    assert abs(row["start_lat"] - 38.22240) < 1e-4 and abs(row["start_lon"] + 84.53910) < 1e-4
    assert "track" not in row and "gps_track" not in row

    # overview lists the drive (scalars only, no track array)
    ov = (await client.get("/api/routes?has_track=true")).json()
    assert any(x["id"] == rid and x["has_track"] for x in ov)
    assert all("track" not in x for x in ov)


async def test_empty_or_garbage_track_is_dropped(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    # 0,0 (null island) and out-of-range coords are filtered; empty result => no track stored
    rid = await _ingest_route_with_track(
        client, device_id, keys, name="2026-06-27--11-00-00",
        track=[[0.0, 0.0, 0.0], [1.0, 999.0, 999.0], [2.0, -91.0, 200.0]],
    )
    r = (await client.get(f"/api/routes/{rid}/track")).json()
    assert r["track"] == []
    lst = (await client.get(f"/api/devices/{device_id}/routes")).json()
    assert next(x for x in lst if x["id"] == rid)["has_track"] is False


async def test_track_not_overwritten_by_empty_redeclare(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    rid = await _ingest_route_with_track(client, device_id, keys, name="2026-06-27--12-00-00")
    # re-declare the SAME route with no track — must NOT wipe the stored one
    await device_post(
        client, device_id, keys, "/api/ingest/routes/start",
        {"name": "2026-06-27--12-00-00", "files": [{"segment_index": 0, "name": "qlog.zst", "kind": "qlog"}]},
    )
    assert (await client.get(f"/api/routes/{rid}/track")).json()["track"] == TRACK


async def test_track_owner_isolation(client):
    """User A must never see user B's track or overview (the core privacy guarantee)."""
    from app.db import SessionLocal
    from app.models import Device, DeviceKey, DeviceStatusValue, KeyStatus, Route, User
    from app.security import hash_password
    from mypilot_protocol.crypto import generate_keypair

    # User A (the admin) with a route+track.
    csrf = await setup_admin(client)
    dev_a, keys_a = await pair_device(client, csrf)
    rid_a = await _ingest_route_with_track(client, dev_a, keys_a, name="2026-06-27--13-00-00")

    # A second user created directly in the DB, with their own device + route+track.
    async with SessionLocal() as s:
        ub = User(username="userb", password_hash=hash_password("anotherpass123"), is_admin=True)
        s.add(ub)
        await s.flush()
        kb = generate_keypair()
        devb = Device(owner_id=ub.id, alias="B dev", hardware_id="hw-b", status=DeviceStatusValue.ACTIVE)
        s.add(devb)
        await s.flush()
        s.add(DeviceKey(device_id=devb.id, public_key_b64=kb.public_key_b64, status=KeyStatus.ACTIVE))
        s.add(Route(device_id=devb.id, name="b-route", gps_track=[[0.0, 40.0, -80.0]],
                    start_lat=40.0, start_lon=-80.0))
        await s.commit()
        rid_b = (await s.execute(
            __import__("sqlalchemy").select(Route.id).where(Route.device_id == devb.id)
        )).scalar_one()

    # A is still logged in. A's overview shows ONLY A's route, never B's.
    ov = (await client.get("/api/routes?has_track=true")).json()
    ids = {x["id"] for x in ov}
    assert rid_a in ids
    assert rid_b not in ids, "LEAK: user B's drive appeared in user A's overview"

    # A cannot fetch B's track directly (404, not 403 — the _owned_route contract).
    assert (await client.get(f"/api/routes/{rid_b}/track")).status_code == 404
    # ...nor list B's device routes.
    assert (await client.get(f"/api/devices/{devb.id}/routes")).status_code == 404
