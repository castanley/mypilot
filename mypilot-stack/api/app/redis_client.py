"""Async Redis helpers: presence, rate limiting, one-time pairing codes, and pub/sub.

Functions take an explicit ``redis`` client so they are trivial to unit-test against
``fakeredis``. The live client is created in the app lifespan and stored on ``app.state.redis``.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import Request, WebSocket
from redis.asyncio import Redis

EVENTS_CHANNEL = "mypilot:events"


def get_redis(request: Request) -> Redis:
    """FastAPI dependency: the shared async Redis client."""
    return request.app.state.redis


def get_redis_ws(websocket: WebSocket) -> Redis:
    return websocket.app.state.redis


# --- Presence ----------------------------------------------------------------------------------

def _presence_key(device_id: str) -> str:
    return f"presence:device:{device_id}"


async def mark_online(redis: Redis, device_id: str, ttl: int) -> None:
    await redis.set(_presence_key(device_id), "1", ex=ttl)


async def mark_offline(redis: Redis, device_id: str) -> None:
    await redis.delete(_presence_key(device_id))


async def is_online(redis: Redis, device_id: str) -> bool:
    return bool(await redis.exists(_presence_key(device_id)))


async def online_among(redis: Redis, device_ids: list[str]) -> set[str]:
    """Return the subset of ``device_ids`` currently marked online."""
    if not device_ids:
        return set()
    keys = [_presence_key(d) for d in device_ids]
    values = await redis.mget(keys)
    return {d for d, v in zip(device_ids, values) if v is not None}


# --- Live working-state (write-behind heartbeat coalescing) ------------------------------------
# When heartbeat_persist_interval_seconds > 0 the DeviceStatus row is committed only every N
# seconds, so the cross-beat working trail + the last-persisted clock must survive between beats
# somewhere durable-but-cheap: Redis, TTL'd to presence so they vanish when the device drops.

def _live_track_key(device_id: str) -> str:
    return f"live:track:{device_id}"


def _persisted_at_key(device_id: str) -> str:
    return f"live:persisted_at:{device_id}"


async def get_live_track(redis: Redis, device_id: str) -> list | None:
    raw = await redis.get(_live_track_key(device_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


async def set_live_track(redis: Redis, device_id: str, track: list | None, ttl: int) -> None:
    if track:
        await redis.set(_live_track_key(device_id), json.dumps(track), ex=ttl)
    else:
        await redis.delete(_live_track_key(device_id))


async def get_persisted_at(redis: Redis, device_id: str) -> float | None:
    raw = await redis.get(_persisted_at_key(device_id))
    return float(raw) if raw else None


async def set_persisted_at(redis: Redis, device_id: str, ts: float, ttl: int) -> None:
    await redis.set(_persisted_at_key(device_id), str(ts), ex=ttl)


async def clear_live_state(redis: Redis, device_id: str) -> None:
    """Drop the live working-state keys (on clean offline; they're TTL'd so this is just promptness)."""
    await redis.delete(_live_track_key(device_id), _persisted_at_key(device_id))


# --- Rate limiting (fixed window) --------------------------------------------------------------

async def rate_limit_ok(redis: Redis, key: str, limit: int, window: int) -> bool:
    """Increment a fixed-window counter; return False once it exceeds ``limit``."""
    full_key = f"ratelimit:{key}"
    count = await redis.incr(full_key)
    if count == 1:
        await redis.expire(full_key, window)
    return count <= limit


# --- One-time pairing codes --------------------------------------------------------------------

def _pairing_key(code: str) -> str:
    return f"pairing:code:{code.upper()}"


async def store_pairing_code(redis: Redis, code: str, pairing_id: str, ttl: int) -> None:
    await redis.set(_pairing_key(code), pairing_id, ex=ttl)


async def consume_pairing_code(redis: Redis, code: str) -> str | None:
    """Atomically fetch-and-delete a pairing code -> pairing_id (one-time use)."""
    return await redis.getdel(_pairing_key(code))


# --- Pub/sub event bridge ----------------------------------------------------------------------

async def publish_event(redis: Redis, payload: dict[str, Any]) -> None:
    await redis.publish(EVENTS_CHANNEL, json.dumps(payload))
