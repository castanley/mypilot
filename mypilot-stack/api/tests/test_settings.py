"""Settings system: listing, validation, gating (offroad/danger/capability), audit, results."""

from __future__ import annotations

from .helpers import device_post, pair_device, setup_admin

HEARTBEAT = "/api/devices/self/heartbeat"
SYNC = "/api/devices/self/settings/sync"
RESULT = "/api/devices/self/settings/result"

CAPS = {
    "torque_allowed": True,
    "enable_bsm": True,
    "has_longitudinal_control": False,
    "alpha_long_available": False,
}


async def _prepare(client, *, onroad=False):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    await device_post(client, device_id, keys, HEARTBEAT, {"onroad": onroad})
    await device_post(client, device_id, keys, SYNC, {"capabilities": CAPS, "values": {}})
    return csrf, device_id, keys


def _all_settings(resp_json):
    out = {}
    for panel in resp_json["panels"]:
        for section in panel["sections"]:
            for s in section["settings"]:
                out[s["key"]] = s
    return out


async def test_list_settings_with_capability_filter(client):
    csrf, device_id, keys = await _prepare(client)
    resp = await client.get(f"/api/devices/{device_id}/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["synced"] is True
    settings = _all_settings(data)
    # capability satisfied -> shown
    assert "EnforceTorqueControl" in settings
    assert "BlindSpot" in settings
    # capability NOT satisfied -> hidden
    assert "ExperimentalMode" not in settings  # needs has_longitudinal_control
    assert "AlphaLongitudinalEnabled" not in settings  # needs alpha_long_available
    # a safe setting shows its default
    assert settings["IsMetric"]["current_value"] is False
    assert settings["IsMetric"]["is_default"] is True


async def test_change_apply_and_audit(client):
    csrf, device_id, keys = await _prepare(client)

    resp = await client.post(
            f"/api/devices/{device_id}/settings/IsMetric/change",
            json={"value": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 202, resp.text
    change = resp.json()
    assert change["status"] == "pending"
    change_id = change["id"]

    # device applies + reports result
    res = await device_post(
        client, device_id, keys, RESULT,
        {"change_id": change_id, "key": "IsMetric", "ok": True, "value": True},
    )
    assert res.status_code == 200

    data = (await client.get(f"/api/devices/{device_id}/settings")).json()
    assert _all_settings(data)["IsMetric"]["current_value"] is True
    assert _all_settings(data)["IsMetric"]["is_default"] is False

    actions = [e["action"] for e in (await client.get(f"/api/devices/{device_id}/audit")).json()]
    assert "device.setting.change" in actions
    assert "device.setting.result" in actions


async def test_validation_rejects_bad_values(client):
    csrf, device_id, keys = await _prepare(client)

    async def patch(key, value):
        return await client.post(
                f"/api/devices/{device_id}/settings/{key}/change",
                json={"value": value},
            headers={"X-CSRF-Token": csrf},
        )

    assert (await patch("IsMetric", "yes")).status_code == 400        # not a bool
    assert (await patch("LongitudinalPersonality", 99)).status_code == 400  # bad enum
    assert (await patch("CameraOffset", 10)).status_code == 400       # > max
    assert (await patch("NotARealSetting", True)).status_code == 404  # unknown


async def test_offroad_gating(client):
    csrf, device_id, keys = await _prepare(client, onroad=True)
    # Mads requires offroad -> blocked while onroad
    blocked = await client.post(
            f"/api/devices/{device_id}/settings/Mads/change",
            json={"value": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert blocked.status_code == 403

    # go offroad -> allowed
    await device_post(client, device_id, keys, HEARTBEAT, {"onroad": False})
    ok = await client.post(
            f"/api/devices/{device_id}/settings/Mads/change",
            json={"value": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code == 202


async def test_danger_requires_confirmation(client):
    csrf, device_id, keys = await _prepare(client)  # offroad
    # JoystickDebugMode is dangerous (and offroad-only)
    no_confirm = await client.post(
            f"/api/devices/{device_id}/settings/JoystickDebugMode/change",
            json={"value": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert no_confirm.status_code == 400

    confirmed = await client.post(
            f"/api/devices/{device_id}/settings/JoystickDebugMode/change",
            json={"value": True, "confirm": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 202


async def test_capability_unavailable_rejected(client):
    csrf, device_id, keys = await _prepare(client)
    # ExperimentalMode needs has_longitudinal_control (False on this device)
    resp = await client.post(
            f"/api/devices/{device_id}/settings/ExperimentalMode/change",
            json={"value": True, "confirm": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 409


async def test_arm_on_device_only_gate(client):
    """A web write may turn an arm-on-device-only setting OFF or move it between non-off values, but
    may NOT arm it from off — that requires the device. Mirrors the camera-upload privacy gate."""
    from app.db import SessionLocal
    from app.models import SettingDefinition

    # Seed a gated enum setting (off/preview/full) like drive_upload.
    async with SessionLocal() as s:
        await s.merge(SettingDefinition(
            key="gated_upload", type="enum", label="Gated upload", description="",
            options=[{"value": "off", "label": "Off"}, {"value": "preview", "label": "Preview"},
                     {"value": "full", "label": "Full"}],
            default_value="off", panel="toggles", section="Recording",
            remote_configurable=True, arm_on_device_only=True,
        ))
        await s.commit()

    csrf, device_id, keys = await _prepare(client)

    async def patch(value):
        return await client.post(
                f"/api/devices/{device_id}/settings/gated_upload/change",
                json={"value": value},
            headers={"X-CSRF-Token": csrf},
        )

    # Device value defaults to off -> web cannot arm.
    assert (await patch("full")).status_code == 403
    assert (await patch("preview")).status_code == 403
    # Setting it to off (a no-op-ish off->off) is allowed (not an arm).
    assert (await patch("off")).status_code == 202

    # Device reports it is now "full" (physical toggle) -> web may de-escalate / hold.
    await device_post(client, device_id, keys, SYNC,
                      {"capabilities": CAPS, "values": {"gated_upload": "full"}})
    assert (await patch("preview")).status_code == 202   # de-escalate allowed
    # ...and the web-exposed `gated` flag reflects state: armed now (full) -> not gated.
    settings = _all_settings((await client.get(f"/api/devices/{device_id}/settings")).json())
    assert settings["gated_upload"]["arm_on_device_only"] is True
    assert settings["gated_upload"]["gated"] is False

    # Device back to off -> gated true again, and web arm refused once more.
    await device_post(client, device_id, keys, SYNC,
                      {"capabilities": CAPS, "values": {"gated_upload": "off"}})
    settings = _all_settings((await client.get(f"/api/devices/{device_id}/settings")).json())
    assert settings["gated_upload"]["gated"] is True
    assert (await patch("full")).status_code == 403


async def test_reset_and_csrf(client):
    csrf, device_id, keys = await _prepare(client)
    # missing CSRF -> 403
    no_csrf = await client.post(
        f"/api/devices/{device_id}/settings/IsMetric/change", json={"value": True}
    )
    assert no_csrf.status_code == 403

    reset = await client.post(
        f"/api/devices/{device_id}/settings/IsMetric/reset", headers={"X-CSRF-Token": csrf}
    )
    assert reset.status_code == 202
    assert reset.json()["new_value"] is False  # default
