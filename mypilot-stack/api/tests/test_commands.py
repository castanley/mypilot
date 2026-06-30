"""Command authorization + safety: reboot requires offroad, is audited, and reports results."""

from __future__ import annotations

from .helpers import device_post, pair_device, setup_admin

HEARTBEAT = "/api/devices/self/heartbeat"


async def _reboot(client, device_id, csrf):
    return await client.post(
        f"/api/devices/{device_id}/reboot", headers={"X-CSRF-Token": csrf}
    )


async def test_reboot_blocked_when_onroad(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)

    # Device reports it is onroad.
    await device_post(client, device_id, keys, HEARTBEAT, {"onroad": True})

    resp = await _reboot(client, device_id, csrf)
    assert resp.status_code == 403
    assert "onroad" in resp.json()["detail"].lower()


async def test_reboot_allowed_offroad_and_audited(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    await device_post(client, device_id, keys, HEARTBEAT, {"onroad": False})

    resp = await _reboot(client, device_id, csrf)
    assert resp.status_code == 202, resp.text
    command = resp.json()
    assert command["name"] == "reboot"
    assert command["requires_offroad"] is True
    command_id = command["id"]

    # The action is in the device audit log.
    audit = await client.get(f"/api/devices/{device_id}/audit")
    actions = [e["action"] for e in audit.json()]
    assert "device.command.reboot" in actions

    # The device reports the result via a signed request.
    result = await device_post(
        client,
        device_id,
        keys,
        f"/api/devices/self/commands/{command_id}/result",
        {"ok": True, "detail": "rebooting"},
    )
    assert result.status_code == 200

    audit2 = await client.get(f"/api/devices/{device_id}/audit")
    actions2 = [e["action"] for e in audit2.json()]
    assert "device.command.result" in actions2


async def test_reboot_requires_csrf(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    await device_post(client, device_id, keys, HEARTBEAT, {"onroad": False})

    no_csrf = await client.post(f"/api/devices/{device_id}/reboot")
    assert no_csrf.status_code == 403
