"""Shared test helpers: auth, pairing, and signed device requests."""

from __future__ import annotations

import json

from httpx import AsyncClient
from mypilot_protocol.crypto import KeyPair, generate_keypair, sign
from mypilot_protocol.messages import pairing_challenge
from mypilot_protocol.signing import build_signed_headers

ADMIN_USER = "admin"
ADMIN_PASS = "supersecret123"


async def setup_admin(client: AsyncClient) -> str:
    """Create the first admin and return the CSRF token (cookies set on the client)."""
    resp = await client.post(
        "/api/auth/setup", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["csrf_token"]


async def login(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["csrf_token"]


async def pair_device(
    client: AsyncClient, csrf: str, *, alias: str = "Test device"
) -> tuple[str, KeyPair]:
    """Run the full pairing handshake and return (device_id, keypair) for an active device."""
    keys = generate_keypair()

    start = await client.post(
        "/api/devices/register/start",
        json={"public_key": keys.public_key_b64, "hardware_id": "hw-test", "hostname": "simhost"},
    )
    assert start.status_code == 200, start.text
    pairing_id = start.json()["pairing_id"]
    code = start.json()["code"]

    claim = await client.post(
        "/api/devices/claim",
        json={"code": code, "alias": alias},
        headers={"X-CSRF-Token": csrf},
    )
    assert claim.status_code == 201, claim.text
    device_id = claim.json()["device"]["id"]

    signature = sign(keys.private_key_b64, pairing_challenge(pairing_id))
    complete = await client.post(
        "/api/devices/register/complete",
        json={"pairing_id": pairing_id, "signature": signature},
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == "active"
    assert complete.json()["device_id"] == device_id
    return device_id, keys


async def device_post(
    client: AsyncClient,
    device_id: str,
    keys: KeyPair,
    path: str,
    payload: dict,
    *,
    timestamp: int | None = None,
    tamper: bool = False,
):
    """Issue a signed device request with an exact-byte body."""
    body = json.dumps(payload).encode("utf-8")
    headers = build_signed_headers(
        device_id, keys.private_key_b64, "POST", path, body, timestamp=timestamp
    )
    if tamper:
        headers["X-MyPilot-Signature"] = headers["X-MyPilot-Signature"][:-2] + "AA"
    headers["Content-Type"] = "application/json"
    return await client.post(path, content=body, headers=headers)


async def device_put(
    client: AsyncClient,
    device_id: str,
    keys: KeyPair,
    path: str,
    body: bytes,
    *,
    content_type: str = "application/octet-stream",
):
    """Issue a signed device PUT with a raw-byte body (route/log file uploads)."""
    headers = build_signed_headers(device_id, keys.private_key_b64, "PUT", path, body)
    headers["Content-Type"] = content_type
    return await client.put(path, content=body, headers=headers)


async def device_get(client: AsyncClient, device_id: str, keys: KeyPair, path: str):
    """Issue a signed device GET (e.g. model artifact download)."""
    headers = build_signed_headers(device_id, keys.private_key_b64, "GET", path, b"")
    return await client.get(path, headers=headers)
