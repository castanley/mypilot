"""M6 backups: snapshot -> JSON, list, download, diff, offroad-gated restore, import/migration."""

from __future__ import annotations

import json

from .helpers import device_post, pair_device, setup_admin

HEARTBEAT = "/api/devices/self/heartbeat"
SYNC = "/api/devices/self/settings/sync"


async def _report_setting(client, device_id, dkeys, key, value):
    await device_post(client, device_id, dkeys, SYNC, {"capabilities": {}, "values": {key: value}})


async def test_backup_create_download_diff_restore(client):
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    await device_post(client, device_id, dkeys, HEARTBEAT, {"onroad": False})
    await _report_setting(client, device_id, dkeys, "IsLdwEnabled", True)

    cb = await client.post(
        f"/api/devices/{device_id}/backups", json={"name": "snap1"}, headers={"X-CSRF-Token": csrf}
    )
    assert cb.status_code == 201, cb.text
    bid = cb.json()["id"]
    assert cb.json()["settings_count"] == 1
    assert len(cb.json()["checksum"]) == 64

    lst = await client.get("/api/backups")
    assert any(b["id"] == bid for b in lst.json())

    dl = await client.get(f"/api/backups/{bid}/download")
    assert dl.status_code == 200
    doc = json.loads(dl.content)
    assert doc["settings"]["IsLdwEnabled"] is True

    # Change the live value, then diff against the backup.
    await _report_setting(client, device_id, dkeys, "IsLdwEnabled", False)
    diff = await client.get(f"/api/devices/{device_id}/backups/{bid}/diff")
    assert diff.status_code == 200
    changed = {c["key"]: c for c in diff.json()["changes"]}
    assert "IsLdwEnabled" in changed
    assert changed["IsLdwEnabled"]["backup_value"] is True
    assert changed["IsLdwEnabled"]["current_value"] is False

    # Restore needs confirmation, then queues a restore command.
    r0 = await client.post(
        f"/api/devices/{device_id}/backups/{bid}/restore",
        json={"confirm": False},
        headers={"X-CSRF-Token": csrf},
    )
    assert r0.status_code == 400
    r1 = await client.post(
        f"/api/devices/{device_id}/backups/{bid}/restore",
        json={"confirm": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert r1.status_code == 200, r1.text


async def test_restore_requires_offroad(client):
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    await _report_setting(client, device_id, dkeys, "IsLdwEnabled", True)
    bid = (
        await client.post(
            f"/api/devices/{device_id}/backups", json={}, headers={"X-CSRF-Token": csrf}
        )
    ).json()["id"]
    await device_post(client, device_id, dkeys, HEARTBEAT, {"onroad": True})
    r = await client.post(
        f"/api/devices/{device_id}/backups/{bid}/restore",
        json={"confirm": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 403


async def test_backup_import_migration(client):
    csrf = await setup_admin(client)
    await pair_device(client, csrf)
    payload = {
        "mypilot_backup_version": 1,
        "kind": "settings",
        "source_alias": "Other car",
        "settings": {"IsLdwEnabled": True, "IsMetric": True},
        "capabilities": {},
    }
    imp = await client.post(
        "/api/backups/import",
        content=json.dumps(payload),
        headers={"X-CSRF-Token": csrf, "Content-Type": "application/json"},
    )
    assert imp.status_code == 201, imp.text
    assert imp.json()["settings_count"] == 2
    assert imp.json()["source_alias"] == "Other car"


async def test_backups_require_auth(client):
    csrf = await setup_admin(client)
    device_id, _ = await pair_device(client, csrf)
    client.cookies.clear()
    assert (await client.get("/api/backups")).status_code == 401
    assert (await client.post(f"/api/devices/{device_id}/backups", json={})).status_code == 401
