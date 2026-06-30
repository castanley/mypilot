"""M7 software: release catalog, device state, offroad/confirm gating, update + rollback."""

from __future__ import annotations

from .helpers import device_post, pair_device, setup_admin

HEARTBEAT = "/api/devices/self/heartbeat"
V_OLD = "2025.000.000-old"          # arbitrary device-reported current version
V_NEW = "2026.001.007"              # the seeded 'release' channel version


async def test_releases_catalog(client):
    csrf = await setup_admin(client)
    # Point the deployment at a fork so the catalog's install URLs are populated (defaults are empty).
    await client.patch(
        "/api/admin/config",
        json={"github_owner": "acme", "release_branch": "op", "staging_branch": "op-rc"},
        headers={"X-CSRF-Token": csrf},
    )
    r = await client.get("/api/software/releases")
    assert r.status_code == 200, r.text
    rows = r.json()
    versions = {x["version"] for x in rows}
    channels = {x["channel"] for x in rows}
    assert V_NEW in versions
    assert {"release", "staging"} <= channels
    # Install URLs are derived from the configured fork — real comma-installer host, configured owner.
    assert all("installer.comma.ai/acme/" in (x["install_url"] or "") for x in rows)


async def test_device_software_state(client):
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    await device_post(
        client, device_id, dkeys, HEARTBEAT,
        {"onroad": False, "subsystems": {"software": {"version": V_OLD, "branch": "mypilot-mici"}}},
    )
    r = await client.get(f"/api/devices/{device_id}/software")
    assert r.status_code == 200
    assert r.json()["current_version"] == V_OLD
    assert len(r.json()["releases"]) >= 2


async def test_update_requires_offroad(client):
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    await device_post(client, device_id, dkeys, HEARTBEAT, {"onroad": True})
    r = await client.post(
        f"/api/devices/{device_id}/software/update",
        json={"version": V_NEW, "confirm": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 403


async def test_update_requires_confirm(client):
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    await device_post(client, device_id, dkeys, HEARTBEAT, {"onroad": False, "subsystems": {"software": {"version": V_OLD}}})
    r = await client.post(
        f"/api/devices/{device_id}/software/update",
        json={"version": V_NEW},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 400


async def test_update_and_rollback(client):
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    await device_post(client, device_id, dkeys, HEARTBEAT, {"onroad": False, "subsystems": {"software": {"version": V_OLD}}})

    up = await client.post(
        f"/api/devices/{device_id}/software/update",
        json={"version": V_NEW, "confirm": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert up.status_code == 202, up.text
    assert up.json()["name"] == "software_update"
    await device_post(
        client, device_id, dkeys, f"/api/devices/self/commands/{up.json()['id']}/result", {"ok": True}
    )
    state = await client.get(f"/api/devices/{device_id}/software")
    assert state.json()["current_version"] == V_NEW
    assert state.json()["previous_version"] == V_OLD

    rb = await client.post(
        f"/api/devices/{device_id}/software/rollback", headers={"X-CSRF-Token": csrf}
    )
    assert rb.status_code == 202, rb.text
    await device_post(
        client, device_id, dkeys, f"/api/devices/self/commands/{rb.json()['id']}/result", {"ok": True}
    )
    state2 = await client.get(f"/api/devices/{device_id}/software")
    assert state2.json()["current_version"] == V_OLD

    actions = [
        e["action"] for e in (await client.get(f"/api/devices/{device_id}/audit?limit=40")).json()
    ]
    assert "device.software.update" in actions
    assert "device.software.rollback" in actions
