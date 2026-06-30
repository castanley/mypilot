"""End-to-end guard for the "phantom live map" bug class: a device whose Redis presence has expired
(no clean disconnect) must read as PARKED everywhere, even though its DB row still says online/onroad
with a driving fix. This is the integration test that would have caught the regression — it funnels
every read site through the one presence-clamped serializer.

Reproduces the exact drift observed in production: heartbeat onroad with a driving fix (-> DB
online=True, onroad=True, subsystems.driving set, presence key in Redis), then DELETE the presence
key to simulate a 30s-TTL lapse with no graceful disconnect."""

from __future__ import annotations

from .helpers import device_post, pair_device, setup_admin

HEARTBEAT = "/api/devices/self/heartbeat"

ONROAD_FIX = {
    "onroad": True,
    "subsystems": {
        "gps": {"status": "has_fix"},
        "driving": {"latitude": 37.5, "longitude": -122.3, "speed_ms": 20.0, "heading_deg": 90.0},
    },
}


async def _drive_then_expire(client, app):
    """Pair a device, send an onroad heartbeat (so DB+Redis both show it live driving), then expire
    its Redis presence key to simulate an ungraceful drop. Returns device_id."""
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    hb = await device_post(client, device_id, dkeys, HEARTBEAT, ONROAD_FIX)
    assert hb.status_code == 200, hb.text
    # Sanity: the device's own heartbeat response shows it live + driving.
    assert hb.json()["onroad"] is True
    assert hb.json()["subsystems"]["driving"]["latitude"] == 37.5
    # Simulate the presence TTL lapsing with no clean disconnect (the phantom trigger).
    await app.state.redis.delete(f"presence:device:{device_id}")
    return device_id


async def test_list_detail_status_software_all_parked_when_presence_expired(client, app):
    device_id = await _drive_then_expire(client, app)

    # 1. List endpoint
    lst = await client.get("/api/devices")
    assert lst.status_code == 200
    row = next(d for d in lst.json() if d["id"] == device_id)
    assert row["online"] is False
    assert row["onroad"] is False

    # 2. Detail endpoint — status_detail must be force-parked (no driving mirror, empty trail)
    det = await client.get(f"/api/devices/{device_id}")
    assert det.status_code == 200
    sd = det.json()["status_detail"]
    assert sd["online"] is False
    assert sd["onroad"] is False
    assert (sd.get("subsystems") or {}).get("driving") in (None, {})
    assert sd.get("live_track") in ([], None)

    # 3. /status endpoint (the leak the audit found) — also clamped now
    st = await client.get(f"/api/devices/{device_id}/status")
    assert st.status_code == 200
    assert st.json()["online"] is False
    assert st.json()["onroad"] is False
    assert (st.json().get("subsystems") or {}).get("driving") in (None, {})

    # 4. /software endpoint — onroad hint must not be stuck "onroad" for an offline device
    sw = await client.get(f"/api/devices/{device_id}/software")
    assert sw.status_code == 200
    assert sw.json()["onroad"] is False


async def test_still_live_while_presence_present(client, app):
    """No false negatives: an actually-present onroad device still reads as driving (live map works)."""
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    hb = await device_post(client, device_id, dkeys, HEARTBEAT, ONROAD_FIX)
    assert hb.status_code == 200

    det = await client.get(f"/api/devices/{device_id}")
    sd = det.json()["status_detail"]
    assert sd["online"] is True
    assert sd["onroad"] is True
    assert sd["subsystems"]["driving"]["latitude"] == 37.5
