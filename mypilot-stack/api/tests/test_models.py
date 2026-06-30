"""M5 models: empty production catalog, device-reported models, and switch/rollback on a seeded
model (the production catalog ships empty — no stand-in artifacts)."""

from __future__ import annotations

import hashlib

from app.models_catalog import model_artifact, model_checksum, model_storage_key

from .helpers import device_get, device_post, pair_device, setup_admin

HEARTBEAT = "/api/devices/self/heartbeat"
VER = "1.0.0"


async def _seed_model(key: str, *, default: bool = False, device_types=None) -> None:
    """Insert a real model (row + artifact in storage) so switch/download can be exercised."""
    from app import storage
    from app.db import SessionLocal
    from app.models import Model

    artifact = model_artifact(key, VER)
    await storage.put_object(model_storage_key(key, VER), artifact)
    async with SessionLocal() as db:
        db.add(
            Model(
                key=key,
                name=key.replace("-", " ").title(),
                version=VER,
                checksum=model_checksum(key, VER),
                size_bytes=len(artifact),
                storage_key=model_storage_key(key, VER),
                compatible_device_types=device_types or [],
                is_default=default,
            )
        )
        await db.commit()


async def test_catalog_empty_by_default(client):
    await setup_admin(client)
    r = await client.get("/api/models")
    assert r.status_code == 200
    assert r.json() == []  # production default: no stand-in models


async def test_device_reported_model_shows(client):
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    await device_post(
        client,
        device_id,
        dkeys,
        HEARTBEAT,
        {"onroad": False, "subsystems": {"models": {"active_ref": "supercombo-2026", "installed_refs": ["supercombo-2026"]}}},
    )
    dm = await client.get(f"/api/devices/{device_id}/models")
    assert dm.json()["active_model_key"] == "supercombo-2026"
    # The device-reported model surfaces even with an empty catalog (real, not a facade).
    by_key = {m["key"]: m for m in dm.json()["models"]}
    assert "supercombo-2026" in by_key and by_key["supercombo-2026"]["active"] is True


async def test_model_download_checksum(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    await _seed_model("alt-test")
    r = await device_get(client, device_id, keys, "/api/devices/self/models/alt-test/download")
    assert r.status_code == 200
    assert hashlib.sha256(r.content).hexdigest() == model_checksum("alt-test", VER)


async def test_switch_requires_offroad(client):
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    await _seed_model("alt-test")
    await device_post(client, device_id, dkeys, HEARTBEAT, {"onroad": True})
    r = await client.post(
        f"/api/devices/{device_id}/models/switch",
        json={"model_key": "alt-test", "confirm": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 403


async def test_switch_requires_confirm(client):
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    await _seed_model("alt-test")
    await device_post(client, device_id, dkeys, HEARTBEAT, {"onroad": False})
    r = await client.post(
        f"/api/devices/{device_id}/models/switch",
        json={"model_key": "alt-test"},
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 400


async def test_switch_and_rollback(client):
    csrf = await setup_admin(client)
    device_id, dkeys = await pair_device(client, csrf)
    await _seed_model("stock-test", default=True)
    await _seed_model("alt-test")
    await device_post(
        client,
        device_id,
        dkeys,
        HEARTBEAT,
        {"onroad": False, "subsystems": {"models": {"active_ref": "stock-test", "installed_refs": ["stock-test"]}}},
    )

    sw = await client.post(
        f"/api/devices/{device_id}/models/switch",
        json={"model_key": "alt-test", "confirm": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert sw.status_code == 202, sw.text
    await device_post(
        client, device_id, dkeys, f"/api/devices/self/commands/{sw.json()['id']}/result", {"ok": True}
    )
    assert (await client.get(f"/api/devices/{device_id}/models")).json()["active_model_key"] == "alt-test"

    rb = await client.post(
        f"/api/devices/{device_id}/models/rollback", headers={"X-CSRF-Token": csrf}
    )
    assert rb.status_code == 202, rb.text
    await device_post(
        client, device_id, dkeys, f"/api/devices/self/commands/{rb.json()['id']}/result", {"ok": True}
    )
    assert (await client.get(f"/api/devices/{device_id}/models")).json()["active_model_key"] == "stock-test"

    actions = [
        e["action"] for e in (await client.get(f"/api/devices/{device_id}/audit?limit=30")).json()
    ]
    assert "device.model.switch" in actions and "device.model.rollback" in actions
