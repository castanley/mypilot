"""Drive replay: feed a recorded route's GPS track through a SIMULATED device as live telemetry so
speed/heading/position features can be exercised without driving.

Pure helpers (speed/heading from consecutive track points) are unit-tested; ``run_replay`` is the
in-process async loop that writes the sim's DeviceStatus + publishes a realtime event per step.

Track points are ``[t, lat, lon]`` where ``t`` is seconds into the drive (the same shape stored in
Route.gps_track). Speed is Δdistance/Δt between consecutive points; heading is their bearing.
"""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone

from .config import get_settings
from .db import SessionLocal
from .device_service import status_event_payload, update_live_track
from .models import DeviceStatus
from .redis_client import mark_offline, mark_online, publish_event

log = logging.getLogger(__name__)

# device_id -> asyncio.Task, so we can guard against double-starts and cancel a running replay.
_active: dict[str, asyncio.Task] = {}

_EARTH_M = 6_371_000.0


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dla, dlo = la2 - la1, lo2 - lo1
    h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
    return 2 * _EARTH_M * math.asin(math.sqrt(h))


def _bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    dlo = math.radians(b[1] - a[1])
    y = math.sin(dlo) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlo)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def step_from(prev: list, cur: list) -> dict:
    """Derive a `driving` subsystem for the move prev -> cur. Both are [t, lat, lon]. Speed is
    Δdist/Δt (0 if Δt<=0); heading is the bearing prev->cur (None if the points coincide)."""
    p, c = (prev[1], prev[2]), (cur[1], cur[2])
    dt = cur[0] - prev[0]
    dist = _haversine_m(p, c)
    speed_ms = round(dist / dt, 2) if dt > 0 else 0.0
    heading = round(_bearing_deg(p, c), 1) if dist > 0.5 else None
    return {
        "speed_ms": speed_ms,
        "heading_deg": heading,
        "latitude": round(cur[1], 6),
        "longitude": round(cur[2], 6),
        "accuracy_m": 3.0,
    }


def is_replaying(device_id: str) -> bool:
    t = _active.get(device_id)
    return t is not None and not t.done()


async def _write_status(redis, device_id: str, *, onroad: bool, driving: dict | None,
                        replaying: bool) -> None:
    """Persist the sim's status (telemetry envelope) and publish the realtime event."""
    async with SessionLocal() as db:
        status = await db.get(DeviceStatus, device_id)
        if status is None:
            return
        now = datetime.now(timezone.utc)
        subsystems = {"gps": {"status": "has_fix" if driving else "no_signal"}}
        if driving is not None:
            subsystems["driving"] = driving
        status.online = True
        status.onroad = onroad
        status.last_heartbeat_at = now
        status.telemetry = {
            "captured_at": now.isoformat(),
            "onroad": onroad,
            "replaying": replaying,
            "subsystems": subsystems,
        }
        # Same accumulating trail as real devices, so the sim draws a live blue polyline too.
        update_live_track(status, onroad, driving)
        await db.commit()
        await db.refresh(status)
        # A replaying sim is "present" — mark Redis presence so the API (which derives online from
        # Redis, and now gates onroad on online) reports it online; clear it when the replay parks.
        if onroad:
            await mark_online(redis, device_id, get_settings().presence_ttl_seconds)
        else:
            await mark_offline(redis, device_id)
        await publish_event(redis, await status_event_payload(redis, device_id, status))


async def run_replay(redis, device_id: str, track: list, *, speed_factor: float = 1.0,
                     max_step_s: float = 2.0) -> None:
    """Walk ``track`` ([t,lat,lon] points) through the sim device as live telemetry, then park it.
    Sleeps the inter-point Δt / speed_factor (capped at max_step_s so long stationary gaps don't
    stall the replay). Best-effort; always parks the device in the finally so it never sticks
    'driving'. Assumes the caller already verified the device is simulated + owned."""
    try:
        if len(track) < 2:
            return
        for i in range(1, len(track)):
            prev, cur = track[i - 1], track[i]
            await _write_status(redis, device_id, onroad=True,
                                driving=step_from(prev, cur), replaying=True)
            dt = max(0.0, (cur[0] - prev[0])) / max(0.01, speed_factor)
            await asyncio.sleep(min(dt, max_step_s))
    except asyncio.CancelledError:
        raise
    finally:
        # Park: clear onroad + driving + replaying so the sim returns to idle even on cancel/error.
        # Kill Redis presence FIRST and unconditionally — it survives a DB-write failure below, and
        # once presence is gone status_dict() clamps every read + the reaper heals the row. Log
        # failures instead of swallowing them (a silent park failure is how a sim wedged "online").
        try:
            await mark_offline(redis, device_id)
        except Exception:  # noqa: BLE001
            log.exception("replay park: mark_offline failed for %s", device_id)
        try:
            await _write_status(redis, device_id, onroad=False, driving=None, replaying=False)
        except Exception:  # noqa: BLE001
            log.exception("replay park: status write failed for %s", device_id)
        _active.pop(device_id, None)  # don't leak completed tasks in the registry


async def start_replay(redis, device_id: str, track: list, **kw) -> None:
    """Spawn run_replay as a background task, cancelling AND awaiting any prior replay first so its
    park `finally` (mark_offline + status write) completes before the new run calls mark_online —
    otherwise the old task's park could race in after the new task marks the sim online and leave it
    wedged offline."""
    old = _active.get(device_id)
    if old is not None and not old.done():
        old.cancel()
        try:
            await old
        except asyncio.CancelledError:
            pass
    _active[device_id] = asyncio.create_task(run_replay(redis, device_id, track, **kw))


async def stop_replay(device_id: str) -> bool:
    """Cancel a running replay (if any). Returns True if one was cancelled."""
    t = _active.get(device_id)
    if t is not None and not t.done():
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        return True
    return False
