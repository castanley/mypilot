"""In-process WebSocket registry plus a Redis pub/sub bridge to fan device events out to
browser sessions.

Device events are published to Redis (``mypilot:events``); a single subscriber task per
process reads them and pushes to all connected browser WebSockets. Routing events through
Redis keeps a single fan-out path. Commands to a device are sent directly to that device's
socket.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, WebSocket

from ..redis_client import EVENTS_CHANNEL

log = logging.getLogger("mypilot.realtime")


# A single browser socket that has stopped reading must not stall fan-out to the others — cap each
# send so a wedged client is dropped instead of blocking the event loop (head-of-line blocking).
_WEB_SEND_TIMEOUT_S = 5.0


class ConnectionManager:
    def __init__(self) -> None:
        # Browser sockets are indexed BY owner (user_id -> that user's sockets) so a device event
        # fans out in O(owner's sockets) instead of scanning every connected socket per event. The
        # owner tag also enforces owner-scoped delivery: a device event reaches only its owner, never
        # every logged-in user (which would leak telemetry + real-time location).
        self._web: dict[int, set[WebSocket]] = {}
        self._devices: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    # --- browser sockets ---
    async def add_web(self, ws: WebSocket, user_id: int) -> None:
        async with self._lock:
            self._web.setdefault(user_id, set()).add(ws)

    async def remove_web(self, ws: WebSocket) -> None:
        async with self._lock:
            self._discard_web_locked(ws)

    def _discard_web_locked(self, ws: WebSocket) -> None:
        """Remove a socket from whichever owner bucket holds it (caller holds the lock)."""
        for uid, socks in list(self._web.items()):
            if ws in socks:
                socks.discard(ws)
                if not socks:
                    del self._web[uid]
                return

    async def broadcast_web(self, event: dict[str, Any], owner_id: int | None) -> None:
        """Send an event only to sockets whose user owns the device it concerns. ``owner_id`` is the
        device's owner; when it can't be resolved (None) the event is dropped, never broadcast — a
        fail-closed default so an ownership-lookup miss can't leak telemetry to non-owners.

        Sends run concurrently with a per-socket timeout so one slow/backpressured browser can't
        head-of-line-block delivery to everyone else; sockets that error or time out are dropped."""
        if owner_id is None:
            return
        async with self._lock:
            targets = list(self._web.get(owner_id, ()))
        if not targets:
            return

        async def _send(ws: WebSocket) -> WebSocket | None:
            try:
                await asyncio.wait_for(ws.send_json(event), timeout=_WEB_SEND_TIMEOUT_S)
                return None
            except Exception:  # noqa: BLE001 - drop broken/stalled sockets, keep the rest flowing
                return ws

        results = await asyncio.gather(*(_send(ws) for ws in targets))
        dead = [ws for ws in results if ws is not None]
        if dead:
            async with self._lock:
                for ws in dead:
                    self._discard_web_locked(ws)

    # --- device sockets ---
    async def add_device(self, device_id: str, ws: WebSocket) -> None:
        async with self._lock:
            existing = self._devices.get(device_id)
            self._devices[device_id] = ws
        if existing is not None and existing is not ws:
            try:
                await existing.close()
            except Exception:  # noqa: BLE001
                pass

    async def remove_device(self, device_id: str, ws: WebSocket) -> None:
        async with self._lock:
            if self._devices.get(device_id) is ws:
                del self._devices[device_id]

    async def send_to_device(self, device_id: str, frame: dict[str, Any]) -> bool:
        ws = self._devices.get(device_id)
        if ws is None:
            return False
        try:
            await ws.send_json(frame)
            return True
        except Exception:  # noqa: BLE001
            await self.remove_device(device_id, ws)
            return False


async def _resolve_owner(device_id: str, cache: dict[str, int]) -> int | None:
    """device_id -> owner_id, cached. owner_id is immutable for a device row (a device belongs to the
    owner who paired it; re-pairing creates/uses that owner's row), so caching is safe and a cache hit
    avoids a DB round-trip on every heartbeat. Misses hit the DB once. Returns None if unknown."""
    if device_id in cache:
        return cache[device_id]
    # Imported lazily to avoid a circular import at module load (models -> db -> app wiring).
    from ..db import SessionLocal
    from ..models import Device, DeviceStatusValue

    async with SessionLocal() as db:
        device = await db.get(Device, device_id)
    # A revoked (unpaired) device reads as "not found" everywhere in the web (see _owned_device); its
    # events must not surface either. Don't cache it — if it's later re-paired by the same owner the
    # row reactivates and the next lookup resolves cleanly.
    if device is None or device.status == DeviceStatusValue.REVOKED:
        return None
    cache[device_id] = device.owner_id
    return device.owner_id


async def run_event_subscriber(app: FastAPI) -> None:
    """Background task: forward Redis device events to the OWNER's browser WebSockets only."""
    redis = app.state.redis
    manager: ConnectionManager = app.state.manager
    pubsub = redis.pubsub()
    await pubsub.subscribe(EVENTS_CHANNEL)
    log.info("event subscriber listening on %s", EVENTS_CHANNEL)
    owner_cache: dict[str, int] = {}
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                data = json.loads(message["data"])
            except (ValueError, TypeError):
                continue
            device_id = data.get("device_id")
            if not device_id:
                continue  # every device event carries device_id; drop anything that doesn't
            owner_id = await _resolve_owner(device_id, owner_cache)
            # Owner-scoped fan-out: only the device's owner receives it (fail-closed if unknown).
            await manager.broadcast_web(data, owner_id)
    except asyncio.CancelledError:  # graceful shutdown
        raise
    finally:
        try:
            await pubsub.unsubscribe(EVENTS_CHANNEL)
            await pubsub.aclose()
        except Exception:  # noqa: BLE001
            pass
