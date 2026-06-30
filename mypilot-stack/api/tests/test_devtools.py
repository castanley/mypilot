"""Admin dev tools: create/list/delete SIM devices, admin-gating, and the can't-touch-real guard."""

from __future__ import annotations

from .helpers import pair_device, setup_admin

SIM = "/api/admin/dev/sim-devices"


def _csrf_headers(csrf: str) -> dict:
    return {"x-csrf-token": csrf}


async def test_create_list_delete_sim_device(client):
    csrf = await setup_admin(client)

    # create
    r = await client.post(SIM, json={"alias": "Test rig"}, headers=_csrf_headers(csrf))
    assert r.status_code == 201, r.text
    dev = r.json()
    assert dev["is_simulated"] is True
    assert dev["status"] == "active"
    sim_id = dev["id"]

    # it shows in the sim list
    r = await client.get(SIM)
    assert r.status_code == 200
    assert [d["id"] for d in r.json()] == [sim_id]

    # and in the normal device list (so the dashboard sees it, with the SIM flag)
    r = await client.get("/api/devices")
    ids = {d["id"]: d for d in r.json()}
    assert sim_id in ids and ids[sim_id]["is_simulated"] is True

    # delete
    r = await client.request("DELETE", f"{SIM}/{sim_id}", headers=_csrf_headers(csrf))
    assert r.status_code == 200, r.text
    assert (await client.get(SIM)).json() == []


async def test_cannot_delete_a_real_device_via_devtools(client):
    """The dev-tool delete is sim-only — a real paired device must 404, never be removed here."""
    csrf = await setup_admin(client)
    real_id, _keys = await pair_device(client, csrf)

    r = await client.request("DELETE", f"{SIM}/{real_id}", headers=_csrf_headers(csrf))
    assert r.status_code == 404, r.text  # sim-only guard

    # the real device is untouched
    assert (await client.get(f"/api/devices/{real_id}")).status_code == 200


async def test_devtools_require_admin(client, app):
    """A non-admin authenticated user is 403 on the dev tools."""
    csrf = await setup_admin(client)  # creates the first (admin) user + logs in

    # Demote the current user to non-admin and retry.
    from app.db import SessionLocal
    from app.models import User
    from sqlalchemy import select

    async with SessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        user.is_admin = False
        await db.commit()

    assert (await client.get(SIM)).status_code == 403
    r = await client.post(SIM, json={"alias": "x"}, headers=_csrf_headers(csrf))
    assert r.status_code == 403
