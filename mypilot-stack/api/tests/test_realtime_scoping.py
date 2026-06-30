"""Realtime fan-out must be OWNER-SCOPED: a device event reaches only sockets belonging to that
device's owner — never every logged-in user (which would leak telemetry / live location)."""

from __future__ import annotations

import pytest
from app.realtime import ConnectionManager


class FakeWS:
    """Minimal stand-in for a browser WebSocket — records what it received."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


@pytest.mark.asyncio
async def test_broadcast_only_reaches_owner():
    mgr = ConnectionManager()
    alice_ws, bob_ws = FakeWS(), FakeWS()
    await mgr.add_web(alice_ws, user_id=1)  # Alice
    await mgr.add_web(bob_ws, user_id=2)    # Bob

    event = {"type": "device_status", "device_id": "dev-a", "status": {"onroad": True}}
    # owner of dev-a is Alice (user 1)
    await mgr.broadcast_web(event, owner_id=1)

    assert alice_ws.sent == [event]
    assert bob_ws.sent == []  # Bob must NOT see Alice's device telemetry


@pytest.mark.asyncio
async def test_broadcast_fails_closed_on_unknown_owner():
    mgr = ConnectionManager()
    ws = FakeWS()
    await mgr.add_web(ws, user_id=1)
    # owner_id None (lookup miss / revoked device) -> dropped, never broadcast to anyone.
    await mgr.broadcast_web({"type": "device_status", "device_id": "x"}, owner_id=None)
    assert ws.sent == []


@pytest.mark.asyncio
async def test_multiple_sockets_same_owner_all_receive():
    mgr = ConnectionManager()
    tab1, tab2 = FakeWS(), FakeWS()  # same user, two browser tabs
    other = FakeWS()
    await mgr.add_web(tab1, user_id=7)
    await mgr.add_web(tab2, user_id=7)
    await mgr.add_web(other, user_id=8)

    event = {"type": "presence", "device_id": "d", "online": True}
    await mgr.broadcast_web(event, owner_id=7)

    assert tab1.sent == [event] and tab2.sent == [event]
    assert other.sent == []


@pytest.mark.asyncio
async def test_slow_socket_does_not_block_others_and_is_dropped(monkeypatch):
    """A backpressured browser socket must not head-of-line-block the fleet's fan-out: sends run
    concurrently with a per-socket timeout, and the stalled socket is dropped while the rest deliver."""
    import asyncio as _asyncio

    from app.realtime import manager as mgr_mod

    monkeypatch.setattr(mgr_mod, "_WEB_SEND_TIMEOUT_S", 0.05)  # keep the test fast

    class StalledWS:
        def __init__(self):
            self.sent = []

        async def send_json(self, data):
            await _asyncio.sleep(10)  # never completes within the timeout

    mgr = ConnectionManager()
    fast, stalled = FakeWS(), StalledWS()
    await mgr.add_web(fast, user_id=1)
    await mgr.add_web(stalled, user_id=1)

    event = {"type": "device_status", "device_id": "d", "status": {"onroad": True}}
    await mgr.broadcast_web(event, owner_id=1)

    assert fast.sent == [event]                 # fast client got it despite the stalled peer
    assert mgr._web.get(1, set()) == {fast}     # stalled socket was dropped, fast retained


@pytest.mark.asyncio
async def test_resolve_owner_caches_and_skips_revoked(app):
    """_resolve_owner returns the owner for an active device (cached), None for a revoked one."""
    from app.db import SessionLocal
    from app.models import Device, DeviceStatusValue, User
    from app.realtime.manager import _resolve_owner
    from app.security import hash_password

    async with SessionLocal() as db:
        user = User(username="owner1", password_hash=hash_password("x" * 10), is_admin=True)
        db.add(user)
        await db.flush()
        db.add(Device(id="dev-active", owner_id=user.id, alias="A",
                      status=DeviceStatusValue.ACTIVE))
        db.add(Device(id="dev-revoked", owner_id=user.id, alias="R",
                      status=DeviceStatusValue.REVOKED))
        await db.commit()
        uid = user.id

    cache: dict[str, int] = {}
    assert await _resolve_owner("dev-active", cache) == uid
    assert cache.get("dev-active") == uid          # cached after first lookup
    assert await _resolve_owner("dev-revoked", cache) is None  # revoked -> no fan-out
    assert "dev-revoked" not in cache              # and not cached
    assert await _resolve_owner("dev-missing", cache) is None  # unknown -> None
