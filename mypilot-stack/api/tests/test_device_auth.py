"""Signed device-request authentication: valid, tampered, stale, unknown, and revoked."""

from __future__ import annotations

import time

from .helpers import device_post, pair_device, setup_admin

HEARTBEAT = "/api/devices/self/heartbeat"


async def test_valid_signed_heartbeat(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)

    resp = await device_post(
        client, device_id, keys, HEARTBEAT,
        {"onroad": False, "subsystems": {"storage": {"used_pct": 42.0}}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["online"] is True
    assert resp.json()["subsystems"]["storage"]["used_pct"] == 42.0


async def test_driving_telemetry_roundtrips(client):
    """Live driving telemetry (speed/heading/position) ingests, stores, and serializes back through
    the device-status path — distinct from the gps subsystem, all fields preserved."""
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)

    resp = await device_post(
        client, device_id, keys, HEARTBEAT,
        {"onroad": True, "subsystems": {
            "gps": {"status": "has_fix"},
            "driving": {"speed_ms": 13.4, "heading_deg": 87.5,
                        "latitude": 40.1, "longitude": -74.2, "accuracy_m": 3.0},
        }},
    )
    assert resp.status_code == 200, resp.text
    sub = resp.json()["subsystems"]
    assert sub["driving"]["speed_ms"] == 13.4
    assert sub["driving"]["heading_deg"] == 87.5
    assert sub["driving"]["latitude"] == 40.1
    # driving must NOT pollute the gps subsystem (separate schema, not the shared StatusOnly)
    assert sub["gps"]["status"] == "has_fix"
    assert "speed_ms" not in sub["gps"]


async def test_heartbeat_without_driving_subsystem(client):
    """A device that doesn't report driving (offroad / older agent) still ingests cleanly."""
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)

    resp = await device_post(
        client, device_id, keys, HEARTBEAT,
        {"onroad": False, "subsystems": {"gps": {"status": "no_signal"}}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["subsystems"].get("driving") in (None, {})


async def test_tampered_signature_rejected(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    resp = await device_post(client, device_id, keys, HEARTBEAT, {"onroad": False}, tamper=True)
    assert resp.status_code == 401


async def test_stale_timestamp_rejected(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    old = int(time.time()) - 3600
    resp = await device_post(client, device_id, keys, HEARTBEAT, {"onroad": False}, timestamp=old)
    assert resp.status_code == 401


async def test_unknown_device_rejected(client):
    csrf = await setup_admin(client)
    _device_id, keys = await pair_device(client, csrf)
    resp = await device_post(client, "deadbeefdeadbeef", keys, HEARTBEAT, {"onroad": False})
    assert resp.status_code == 401


async def test_revoked_device_rejected(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)

    # Heartbeat works before revocation.
    ok = await device_post(client, device_id, keys, HEARTBEAT, {"onroad": False})
    assert ok.status_code == 200

    revoke = await client.request(
        "DELETE", f"/api/devices/{device_id}", headers={"X-CSRF-Token": csrf}
    )
    assert revoke.status_code == 200

    after = await device_post(client, device_id, keys, HEARTBEAT, {"onroad": False})
    assert after.status_code == 401
