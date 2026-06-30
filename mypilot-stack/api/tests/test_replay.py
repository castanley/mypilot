"""Drive replay: the speed/heading math, the endpoint guards (sim-only, route ownership, no-track),
and a short end-to-end replay that flips the sim's `replaying` flag and parks it afterward."""

from __future__ import annotations

import asyncio

from app.replay_service import _bearing_deg, _haversine_m, step_from

from .helpers import pair_device, setup_admin

SIM = "/api/admin/dev/sim-devices"


def _csrf(c):
    return {"x-csrf-token": c}


def test_haversine_and_bearing_basic():
    # ~111km per degree of latitude.
    assert 110_000 < _haversine_m((0.0, 0.0), (1.0, 0.0)) < 112_000
    # Due east bearing ~90, due north ~0.
    assert abs(_bearing_deg((0.0, 0.0), (0.0, 1.0)) - 90.0) < 1.0
    assert _bearing_deg((0.0, 0.0), (1.0, 0.0)) < 1.0 or _bearing_deg((0.0, 0.0), (1.0, 0.0)) > 359.0


def test_step_from_derives_speed_and_heading():
    # 1 degree lon at the equator in 100s -> fast; heading ~east.
    step = step_from([0.0, 0.0, 0.0], [100.0, 0.0, 1.0])
    assert step["speed_ms"] > 1000  # ~1113 m/s (synthetic), just checks Δdist/Δt
    assert abs(step["heading_deg"] - 90.0) < 1.0
    assert step["latitude"] == 0.0 and step["longitude"] == 1.0


def test_step_from_no_movement_nulls_heading():
    step = step_from([0.0, 37.0, -122.0], [1.0, 37.0, -122.0])
    assert step["speed_ms"] == 0.0
    assert step["heading_deg"] is None


async def test_replay_requires_sim_target(client):
    """Replaying onto a REAL device is a 404 (sim-only)."""
    csrf = await setup_admin(client)
    real_id, _ = await pair_device(client, csrf)
    r = await client.post(f"{SIM}/{real_id}/replay", json={"route_id": "x"}, headers=_csrf(csrf))
    assert r.status_code == 404


async def test_replay_unknown_route_404(client):
    csrf = await setup_admin(client)
    sim = (await client.post(SIM, json={"alias": "rig"}, headers=_csrf(csrf))).json()
    r = await client.post(f"{SIM}/{sim['id']}/replay",
                          json={"route_id": "nope"}, headers=_csrf(csrf))
    assert r.status_code == 404


async def test_replay_end_to_end_sets_and_clears_replaying(client, app):
    """A short replay flips the sim's status to onroad+replaying, then parks it when finished."""
    csrf = await setup_admin(client)
    sim = (await client.post(SIM, json={"alias": "rig"}, headers=_csrf(csrf))).json()
    sim_id = sim["id"]

    # Seed a tiny route owned by the admin's sim device with a 3-point track.
    from app.db import SessionLocal
    from app.models import Route

    async with SessionLocal() as db:
        db.add(Route(
            id="r-replay", device_id=sim_id, name="2026-01-01--00-00-00",
            gps_track=[[0.0, 37.0, -122.0], [1.0, 37.0001, -122.0], [2.0, 37.0002, -122.0]],
        ))
        await db.commit()

    # speed_factor 2x with 1s gaps -> ~0.5s between points, so the replay stays live long enough to
    # observe mid-walk deterministically (3 points ~ 1s total).
    r = await client.post(f"{SIM}/{sim_id}/replay",
                          json={"route_id": "r-replay", "speed_factor": 2.0}, headers=_csrf(csrf))
    assert r.status_code == 200, r.text
    assert r.json()["points"] == 3

    # Mid-walk: the device reports onroad + replaying (poll briefly to avoid a tight race).
    saw_replaying = False
    for _ in range(10):
        await asyncio.sleep(0.05)
        sd = (await client.get(f"/api/devices/{sim_id}")).json()["status_detail"]
        if sd and sd["replaying"] and sd["onroad"]:
            saw_replaying = True
            break
    assert saw_replaying, "never observed the device replaying"

    # After it finishes it parks: not replaying, offroad.
    for _ in range(20):
        await asyncio.sleep(0.1)
        sd = (await client.get(f"/api/devices/{sim_id}")).json()["status_detail"]
        if not sd["replaying"] and not sd["onroad"]:
            break
    assert sd["replaying"] is False
    assert sd["onroad"] is False
