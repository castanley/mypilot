"""Device pairing handshake: start, claim, complete, and failure modes."""

from __future__ import annotations

from mypilot_protocol.crypto import generate_keypair, sign
from mypilot_protocol.messages import pairing_challenge

from .helpers import pair_device, setup_admin


async def test_full_pairing_flow(client):
    csrf = await setup_admin(client)
    device_id, _keys = await pair_device(client, csrf, alias="Garage three")

    devices = await client.get("/api/devices")
    assert devices.status_code == 200
    listing = devices.json()
    assert len(listing) == 1
    assert listing[0]["id"] == device_id
    assert listing[0]["alias"] == "Garage three"
    assert listing[0]["status"] == "active"


async def test_complete_is_pending_before_claim(client):
    await setup_admin(client)
    keys = generate_keypair()
    start = await client.post(
        "/api/devices/register/start",
        json={"public_key": keys.public_key_b64, "hardware_id": "hw", "hostname": "h"},
    )
    pairing_id = start.json()["pairing_id"]

    signature = sign(keys.private_key_b64, pairing_challenge(pairing_id))
    complete = await client.post(
        "/api/devices/register/complete",
        json={"pairing_id": pairing_id, "signature": signature},
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "pending"


async def test_pairing_code_is_one_time(client):
    csrf = await setup_admin(client)
    keys = generate_keypair()
    start = await client.post(
        "/api/devices/register/start",
        json={"public_key": keys.public_key_b64, "hardware_id": "hw", "hostname": "h"},
    )
    code = start.json()["code"]

    first = await client.post(
        "/api/devices/claim", json={"code": code}, headers={"X-CSRF-Token": csrf}
    )
    assert first.status_code == 201
    # The same code cannot be reused.
    second = await client.post(
        "/api/devices/claim", json={"code": code}, headers={"X-CSRF-Token": csrf}
    )
    assert second.status_code == 400


async def test_complete_rejects_bad_signature(client):
    csrf = await setup_admin(client)
    keys = generate_keypair()
    start = await client.post(
        "/api/devices/register/start",
        json={"public_key": keys.public_key_b64, "hardware_id": "hw", "hostname": "h"},
    )
    pairing_id = start.json()["pairing_id"]
    code = start.json()["code"]

    await client.post("/api/devices/claim", json={"code": code}, headers={"X-CSRF-Token": csrf})

    # Sign with a DIFFERENT key than the one registered.
    attacker = generate_keypair()
    bad_sig = sign(attacker.private_key_b64, pairing_challenge(pairing_id))
    complete = await client.post(
        "/api/devices/register/complete",
        json={"pairing_id": pairing_id, "signature": bad_sig},
    )
    assert complete.status_code == 401
