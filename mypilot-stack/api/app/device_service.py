"""Shared device telemetry/command logic used by both the REST endpoints and the WebSocket
handler, so the two transports behave identically."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from mypilot_protocol.telemetry import (
    GPS_STATUSES,
    PANDA_STATUSES,
    THERMAL_STATUSES,
    UPDATE_STATES,
    norm_enum,
)
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import record_audit
from .config import get_settings
from .db import SessionLocal
from .models import CommandResult, CommandStatus, Device, DeviceCommand, DeviceStatus
from .redis_client import (
    clear_live_state,
    get_live_track,
    get_persisted_at,
    mark_offline,
    mark_online,
    online_among,
    publish_event,
    set_live_track,
    set_persisted_at,
)
from .schemas import HeartbeatRequest

log = logging.getLogger(__name__)
settings = get_settings()


def _normalize_enums(payload: HeartbeatRequest) -> None:
    """Coerce subsystem enum fields to their closed sets on ingest (out-of-set -> None), per the
    telemetry contract — don't trust the producer to have done it. Mutates payload in place; covers
    both the WS and REST heartbeat paths since both call apply_heartbeat."""
    sub = payload.subsystems
    if sub.thermal is not None:
        sub.thermal.status = norm_enum(sub.thermal.status, THERMAL_STATUSES)
    if sub.gps is not None:
        sub.gps.status = norm_enum(sub.gps.status, GPS_STATUSES)
    if sub.panda is not None:
        sub.panda.status = norm_enum(sub.panda.status, PANDA_STATUSES)
    if sub.software is not None:
        sub.software.update_state = norm_enum(sub.software.update_state, UPDATE_STATES)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# The trail is kept bounded by simplification, not truncation: when it reaches the soft ceiling we
# Douglas-Peucker it so its size tracks the route's SHAPE, not the drive's DURATION (straight stretches
# collapse to a few points; curves keep detail). Crucially we simplify only OCCASIONALLY (on reaching
# the ceiling), NOT every heartbeat — DP is O(n^2), so per-append simplification would burn the server
# on a long drive. Between simplifies the trail just appends (O(1)).
_LIVE_TRACK_SIMPLIFY_AT = 1500   # simplify when the trail reaches this many points
_LIVE_TRACK_SIMPLIFY_TOL_M = 12.0  # max deviation a simplified segment may hide (~half a lane width)
# Hard backstop: if even simplified the trail somehow stays huge (a genuinely 1500-curve drive), cap
# it, keeping the MOST RECENT points so any truncation is at the least-interesting start.
_LIVE_TRACK_MAX = 4000
# Don't append a point unless the device moved at least this far — drops parked GPS jitter and keeps
# the trail from densifying while stopped at a light (mirrors the route-track philosophy).
_LIVE_TRACK_MIN_MOVE_M = 8.0
_DEG_M = 111_320.0  # metres per degree latitude (good enough for these small-scale point deltas)


def _coarse_far(a: list, b: list, min_m: float) -> bool:
    """Cheap ~meters check (equirectangular) for whether b is at least min_m from a. Avoids importing
    a full haversine on the hot heartbeat path; accurate enough at the scale of a few metres."""
    import math
    dlat = (b[0] - a[0]) * _DEG_M
    dlon = (b[1] - a[1]) * _DEG_M * math.cos(math.radians(a[0]))
    return (dlat * dlat + dlon * dlon) >= (min_m * min_m)


def _simplify(points: list, tol_m: float) -> list:
    """Douglas-Peucker line simplification on [lat, lon] points. Drops vertices that lie within ~tol_m
    of the line between their neighbours, so a near-straight run collapses to its endpoints while
    curves are preserved. Iterative (no recursion-depth risk on long tracks). Endpoints always kept."""
    import math
    n = len(points)
    if n < 3:
        return list(points)
    # Local planar projection (metres) around the track's first point — accurate at city/route scale.
    lat0 = math.radians(points[0][0])
    coslat = math.cos(lat0)

    def xy(p):
        return (p[1] * _DEG_M * coslat, p[0] * _DEG_M)

    pts_xy = [xy(p) for p in points]

    def perp(i, a, b):
        (x, y), (x1, y1), (x2, y2) = pts_xy[i], pts_xy[a], pts_xy[b]
        dx, dy = x2 - x1, y2 - y1
        seg2 = dx * dx + dy * dy
        if seg2 == 0:
            return math.hypot(x - x1, y - y1)
        t = ((x - x1) * dx + (y - y1) * dy) / seg2
        t = max(0.0, min(1.0, t))
        return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))

    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        dmax, idx = -1.0, -1
        for i in range(a + 1, b):
            d = perp(i, a, b)
            if d > dmax:
                dmax, idx = d, i
        if dmax > tol_m and idx != -1:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [points[i] for i in range(n) if keep[i]]


def _next_live_track(current: list | None, onroad: bool, driving: dict | None) -> list | None:
    """Pure trail update: given the current trail, return the next one. Clears (None) when offroad;
    else appends the current [lat, lon] if it's a valid fix far enough from the last point; returns
    the trail unchanged when there's nothing to add. Simplifies (Douglas-Peucker) once past a
    threshold so it scales to long drives, with a hard cap backstop. Storage-agnostic — works whether
    the trail lives on the ORM row (replay/every-beat path) or in Redis (write-behind path)."""
    if not onroad:
        return None
    lat = (driving or {}).get("latitude")
    lon = (driving or {}).get("longitude")
    if lat is None or lon is None:
        return current
    pt = [round(float(lat), 6), round(float(lon), 6)]
    track = list(current or [])
    if track and not _coarse_far(track[-1], pt, _LIVE_TRACK_MIN_MOVE_M):
        return track
    track.append(pt)
    # Append is O(1) every beat. Only when the trail reaches the soft ceiling do we pay the O(n^2)
    # Douglas-Peucker once to collapse near-straight runs — so size follows route shape, not duration,
    # without re-simplifying on every heartbeat. Hard cap is a final backstop.
    if len(track) >= _LIVE_TRACK_SIMPLIFY_AT:
        track = _simplify(track, _LIVE_TRACK_SIMPLIFY_TOL_M)
        if len(track) > _LIVE_TRACK_MAX:
            track = track[-_LIVE_TRACK_MAX:]
    return track


def update_live_track(status: DeviceStatus, onroad: bool, driving: dict | None) -> None:
    """Maintain status.live_track in place (replay sim + the every-beat heartbeat path)."""
    status.live_track = _next_live_track(status.live_track, onroad, driving)


def status_dict(status: DeviceStatus, online: bool) -> dict:
    """The DeviceStatusOut-shaped dict, CLAMPED to Redis presence — the ONE place liveness is decided.

    `online` is the AUTHORITATIVE presence (from online_among / mark_online), NOT status.online (the
    raw DB column, which lags a TTL expiry). It is a required arg so no caller can serialize a device
    to the wire without supplying the Redis truth. An offline device is force-parked here: onroad
    False, the live `driving` position mirror dropped, replaying cleared, trail emptied. This single
    chokepoint feeds the REST summary/detail, the /status endpoint, and the realtime device_status
    event, so a stale onroad/driving snapshot ("phantom" live map on a parked/offline device) can
    never be served from any path. The realtime web merge is shallow, so the FULL `subsystems` tree
    must be present (the device sends it whole each heartbeat) — never a partial delta."""
    t = status.telemetry or {}
    onroad = bool(online and status.onroad)  # offline => never onroad
    subsystems = t.get("subsystems")
    if not onroad and subsystems and subsystems.get("driving"):
        subsystems = {**subsystems, "driving": None}  # drop the live position mirror when not driving
    return {
        "online": online,  # authoritative (Redis presence), never the raw status.online column
        "onroad": onroad,
        "last_heartbeat_at": _iso(status.last_heartbeat_at),
        "updated_at": _iso(status.updated_at),
        "captured_at": t.get("captured_at"),
        "subsystems": subsystems,
        # True while an admin drive-replay is feeding this (simulated) device — clients show a
        # "Replaying" indicator. Absent/false on real devices and idle sims; cleared when offline.
        "replaying": bool(online and t.get("replaying", False)),
        # Accumulating [lat, lon] trail for the current drive (blue polyline on the live map).
        "live_track": (status.live_track or []) if onroad else [],
    }


async def status_event_payload(
    redis: Redis, device_id: str, status: DeviceStatus, online: bool | None = None
) -> dict:
    """Realtime device_status event, presence-clamped via the SAME serializer as REST — so the
    realtime path can never be the hole stale onroad/driving crawls back through.

    `online` lets a caller that ALREADY knows live presence (e.g. apply_heartbeat just ran
    mark_online) skip a redundant Redis MGET on the hot path; when None we resolve it here."""
    if online is None:
        online = device_id in await online_among(redis, [device_id])
    return {"type": "device_status", "device_id": device_id, "status": status_dict(status, online)}


def _mirror_device_header(device: Device, payload: HeartbeatRequest) -> None:
    """Mirror the few fields the device LIST/detail header needs onto Device, pulled from the
    envelope's subsystems (software/platform/models). Only overwrite when the device reported a value,
    so a partial heartbeat never clears known state."""
    sub = payload.subsystems
    sw = sub.software
    if sw is not None:
        if sw.version:
            device.software_version = sw.version
        if sw.branch:
            device.branch = sw.branch
        if sw.update_channel is not None:
            device.update_channel = sw.update_channel
    if sub.platform is not None and sub.platform.name:
        device.platform = sub.platform.name
    if sub.models is not None and sub.models.active_ref is not None:
        device.active_model_key = sub.models.active_ref


async def apply_heartbeat(
    db: AsyncSession, redis: Redis, device: Device, payload: HeartbeatRequest
) -> DeviceStatus:
    """Upsert the device's status snapshot, refresh presence, and fan out the realtime event.

    The realtime WS event is built from THIS beat's in-hand data and published every beat — the live
    map is real-time regardless of when the DB row is committed. With heartbeat_persist_interval>0 the
    DeviceStatus row is committed only on a coalesced cadence (write-behind): the working trail +
    last-persisted clock live in Redis between beats, cutting Postgres write volume ~10x at fleet
    scale. interval==0 (default) commits every beat — today's exact behavior."""
    now = datetime.now(timezone.utc)
    _normalize_enums(payload)  # enforce the closed enum sets on ingest (never trust the producer)
    telemetry = payload.model_dump(mode="json")
    driving = telemetry.get("subsystems", {}).get("driving") if telemetry else None
    interval = settings.heartbeat_persist_interval_seconds

    status = await db.get(DeviceStatus, device.id)
    is_new = status is None
    onroad_changed = is_new or (status.onroad != payload.onroad)

    if interval > 0:
        # Write-behind: keep the working trail in Redis (presence-TTL'd) so a skipped commit doesn't
        # lose accumulated points. The event is built from this same fresh trail, so the map is live.
        track = _next_live_track(await get_live_track(redis, device.id), payload.onroad, driving)
        await set_live_track(redis, device.id, track, settings.presence_ttl_seconds)
        persisted_at = await get_persisted_at(redis, device.id)
        due = persisted_at is None or (now.timestamp() - persisted_at) >= interval
        # Force a persist on correctness boundaries: brand-new row, or an onroad transition (so the
        # durable row never sits on a stale onroad flag that other consumers / a reaper-less read see).
        should_persist = is_new or onroad_changed or due
    else:
        track = _next_live_track(status.live_track if status else None, payload.onroad, driving)
        should_persist = True

    if should_persist:
        if status is None:
            status = DeviceStatus(device_id=device.id)
            db.add(status)
        status.online = True
        status.onroad = payload.onroad
        status.last_heartbeat_at = now
        status.telemetry = telemetry
        status.live_track = track
        _mirror_device_header(device, payload)
        await mark_online(redis, device.id, settings.presence_ttl_seconds)
        await db.commit()
        if interval > 0:
            await set_persisted_at(redis, device.id, now.timestamp(), settings.presence_ttl_seconds)
    else:
        # Coalesced beat: no DB write. Still refresh presence (it's the liveness source of truth) and
        # build a transient status snapshot from this beat's data purely to fan out the realtime event.
        await mark_online(redis, device.id, settings.presence_ttl_seconds)
        db.expunge(status)  # detach FIRST so the event-only mutations below can never autoflush
        status.online = True
        status.onroad = payload.onroad
        status.last_heartbeat_at = now
        status.telemetry = telemetry
        status.live_track = track

    # ONE event per beat. The device_status payload carries online=True (the web reducer folds it into
    # node.online), so a separate presence:true publish was pure duplication on the hottest path. We
    # just called mark_online, so pass online=True directly to skip a redundant presence MGET.
    # (set_offline still emits presence:false on disconnect — not redundant, no status event there.)
    await publish_event(redis, await status_event_payload(redis, device.id, status, online=True))
    return status


async def set_offline(db: AsyncSession, redis: Redis, device_id: str) -> None:
    await mark_offline(redis, device_id)
    # Drop the write-behind working-state (trail + persisted clock). They're presence-TTL'd so they'd
    # expire anyway, but clearing on a clean offline is prompt and keeps a re-online drive starting fresh.
    await clear_live_state(redis, device_id)
    status = await db.get(DeviceStatus, device_id)
    if status is not None:
        status.online = False
        # An offline device cannot be onroad — clear the stale driving state so the UI never shows the
        # contradictory "offline but on the road" (the onroad flag is from the last heartbeat and would
        # otherwise persist after the device drops). Also drop the live trail/position.
        status.onroad = False
        if status.telemetry:
            status.telemetry = {**status.telemetry, "onroad": False}
            sub = (status.telemetry.get("subsystems") or {})
            if sub.get("driving"):
                status.telemetry["subsystems"] = {**sub, "driving": None}
        status.live_track = None
        await db.commit()
    await publish_event(redis, {"type": "presence", "device_id": device_id, "online": False})


async def record_command_result(
    db: AsyncSession, redis: Redis, device: Device, command_id: str, ok: bool, detail: str | None
) -> CommandResult | None:
    command = await db.get(DeviceCommand, command_id)
    if command is None or command.device_id != device.id:
        return None

    result = CommandResult(command_id=command_id, ok=ok, detail=detail)
    db.add(result)
    command.status = CommandStatus.DONE if ok else CommandStatus.FAILED
    command.completed_at = datetime.now(timezone.utc)

    # Reconcile mirrored device state on a confirmed model switch / software update. The next
    # heartbeat corroborates this; updating here makes the UI reflect success without waiting.
    if ok and command.name == "switch_model":
        key = (command.args or {}).get("model_key")
        if key:
            device.active_model_key = key
    elif ok and command.name == "software_update":
        version = (command.args or {}).get("version")
        channel = (command.args or {}).get("channel")
        if version:
            device.software_version = version
        if channel:
            device.update_channel = channel
    await record_audit(
        db,
        action="device.command.result",
        actor_type="device",
        actor_id=device.id,
        device_id=device.id,
        metadata={"command_id": command_id, "name": command.name, "ok": ok},
    )
    await db.commit()

    await publish_event(
        redis,
        {
            "type": "device_event",
            "device_id": device.id,
            "event": "command_result",
            "command_id": command_id,
            "name": command.name,
            "ok": ok,
        },
    )
    return result


async def reap_expired_presence(redis: Redis, interval: float = 5.0) -> None:
    """Reconcile DB rows whose Redis presence has EXPIRED with no clean disconnect (ungraceful drop,
    a wedged sim) — the gap set_offline never sees, because nothing fires it on a mere TTL lapse.

    status_dict() already clamps every read to live presence, so REST/realtime reads are safe even
    without this. But the client store hides the live-map hero mid-drive on a `presence:false` EVENT
    (a backgrounded tab won't resync promptly), and the DB row would otherwise read online=True for
    other consumers. This sweep finds rows the DB thinks are online but Redis says are gone, and runs
    set_offline (which clears onroad/driving/track AND emits the presence:false event the client
    trusts). Bounds phantom lifetime to ~TTL+interval; only scans the small online=True set; idempotent
    (a duplicate offline event is harmless — the client clamp is idempotent)."""
    while True:
        try:
            async with SessionLocal() as db:
                # Select ONLY device_id — never hydrate the full DeviceStatus rows (each carries the
                # telemetry JSON blob + the up-to-4000-point live_track), which at thousands of online
                # devices would pull megabytes into Python every sweep. We only need the ids to diff
                # against Redis presence; set_offline re-fetches the (few) phantom rows it must clear.
                ids = (
                    await db.execute(
                        select(DeviceStatus.device_id).where(DeviceStatus.online.is_(True))
                    )
                ).scalars().all()
                if ids:
                    live = await online_among(redis, ids)
                    for device_id in ids:
                        if device_id not in live:  # DB says online, Redis presence is gone
                            await set_offline(db, redis, device_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a sweep failure must never kill the loop
            log.exception("presence reaper sweep failed")
        await asyncio.sleep(interval)
