"""Shared device telemetry/command logic used by both the REST endpoints and the WebSocket
handler, so the two transports behave identically."""

from __future__ import annotations

import asyncio
import logging
import math
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
    clear_persisted_at,
    get_last_beat_at,
    get_live_track,
    get_persisted_at,
    mark_offline,
    mark_online,
    online_among,
    publish_event,
    set_last_beat_at,
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
_LIVE_TRACK_SIMPLIFY_TOL_M = 12.0  # base deviation a simplified segment may hide (~half a lane width)
# Target ceiling for the trail's point count. We keep the WHOLE drive end-to-end (never truncate the
# start) by simplifying HARDER when needed: if a pass at the base tolerance still exceeds this, re-run
# Douglas-Peucker at a coarser tolerance until it fits. So a multi-hour drive keeps its full shape at
# a bounded size — the early route is preserved (drawn coarser), not dropped off the front.
_LIVE_TRACK_MAX = 4000
_LIVE_TRACK_TOL_MAX_M = 400.0    # sanity bound on the coarsen-and-retry escalation
# Don't append a point unless the device moved at least this far — drops parked GPS jitter and keeps
# the trail from densifying while stopped at a light (mirrors the route-track philosophy).
_LIVE_TRACK_MIN_MOVE_M = 8.0
_DEG_M = 111_320.0  # metres per degree latitude (good enough for these small-scale point deltas)
# A heartbeat gap longer than this starts a FRESH trail — the accumulated route is now preserved across
# a transient offline (so a cellular drop resumes the same line), so we need a positive signal that a
# genuinely NEW drive has begun. A gap this long is not a blip (cellular drops recover in seconds); it
# means the device was off / parked long enough that the old trail is stale. Comfortably above any
# realistic reconnect gap, well below a short errand's park time.
_LIVE_TRACK_NEW_DRIVE_GAP_S = 180.0


def _finite_point(p: object) -> bool:
    """True iff p is a well-formed [lat, lon] pair with finite, in-range coordinates. The ingest schema
    (DrivingTelemetry) already rejects non-finite/out-of-range at the boundary, but a trail rehydrated
    from Redis/DB can predate that validator (or be corrupted), so the accumulator defends itself: a
    non-finite point that reaches _coarse_far does math.cos(inf) -> ValueError and crashes the heartbeat
    every beat. Cheap enough to run on a single point on the hot path."""
    return (
        isinstance(p, (list, tuple))
        and len(p) == 2
        and isinstance(p[0], (int, float))
        and isinstance(p[1], (int, float))
        and math.isfinite(p[0])
        and math.isfinite(p[1])
        and abs(p[0]) <= 90.0
        and abs(p[1]) <= 180.0
    )


def _coarse_far(a: list, b: list, min_m: float) -> bool:
    """Cheap ~meters check (equirectangular) for whether b is at least min_m from a. Avoids importing
    a full haversine on the hot heartbeat path; accurate enough at the scale of a few metres."""
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


def _simplify_escalate(track: list) -> list:
    """The EXPENSIVE part of the trail update, isolated so the hot path can run it off the event loop.

    Douglas-Peucker is worst-case O(n^2) and an adversarial "sawtooth" trail (every point a local
    extreme — reachable by any authenticated device) makes a single pass take multiple SECONDS at the
    trigger size. Run SYNCHRONOUSLY on the single uvicorn loop that would freeze EVERY device's
    heartbeat/WS for that whole time, so apply_heartbeat offloads this via asyncio.to_thread (see
    _next_live_track_async). It's pure and operates on its own list, so it is safe to run on a worker
    thread. Collapses near-straight runs, escalates the tolerance to keep the WHOLE route bounded rather
    than truncating the start, and hard-caps as a last resort. Returns a trail with len <= MAX."""
    # Belt-and-suspenders: never hand a non-finite point to _simplify — _coarse_far/perp do math.cos on
    # coordinates and a lingering inf/NaN (from a corrupt/legacy trail whose bad point wasn't the tail)
    # would raise math-domain here, on a worker thread, and re-crash the beat. Cheap relative to the DP
    # pass that follows, and this is the rare simplify path (not every beat).
    if not all(_finite_point(p) for p in track):
        track = [p for p in track if _finite_point(p)]
    track = _simplify(track, _LIVE_TRACK_SIMPLIFY_TOL_M)
    # Keep the WHOLE drive: if the base-tolerance pass still exceeds the ceiling (a genuinely long
    # or curvy multi-hour drive), simplify HARDER (coarser tolerance) and retry rather than
    # truncating the start. The early route stays on the map, just drawn coarser. Bounded loop.
    tol = _LIVE_TRACK_SIMPLIFY_TOL_M
    while len(track) > _LIVE_TRACK_MAX and tol < _LIVE_TRACK_TOL_MAX_M:
        tol *= 2.0
        track = _simplify(track, tol)
    # HARD-CAP BACKSTOP: a near-incompressible/noisy track can resist every tolerance up to TOL_MAX
    # and still exceed MAX. Cap to the most-recent MAX points so the stored trail is always bounded
    # (and the next re-simplify trigger is measured against this capped length). Only the
    # pathological incompressible case truncates; a normal drive is kept whole by the escalation.
    if len(track) > _LIVE_TRACK_MAX:
        track = track[-_LIVE_TRACK_MAX:]
    return track


def _append_live_point(current: list | None, onroad: bool, driving: dict | None) -> tuple[list | None, bool]:
    """The CHEAP, O(1) part of the trail update: validate + jitter-gate + append one point. Returns
    (next_trail, simplify_due). simplify_due is True only when the trail has grown to the amortized
    trigger and needs the (expensive) _simplify_escalate pass — which the caller runs inline (sync
    path) or offloads to a thread (hot path). Split out so the O(n^2) simplify never rides the cheap
    every-beat path. See _next_live_track / _next_live_track_async."""
    if not onroad:
        return None, False
    lat = (driving or {}).get("latitude")
    lon = (driving or {}).get("longitude")
    if lat is None or lon is None:
        return current, False
    pt = [round(float(lat), 6), round(float(lon), 6)]
    # Defense in depth against a non-finite/out-of-range coordinate. The ingest schema
    # (DrivingTelemetry) now rejects these at the boundary, but a trail rehydrated from Redis/DB may
    # predate that validator: a poisoned point that reaches _coarse_far/_simplify does math.cos(inf) ->
    # ValueError and crashes the heartbeat (self-sustaining per-device DoS), and a NaN makes every
    # jitter-gate comparison False so no real fix ever appends (frozen trail). Two O(1) hot-path guards
    # cover every EVERY-BEAT crash vector: drop a bad incoming point, and purge the whole trail when its
    # TAIL is non-finite (the only element _coarse_far reads — a bad tail is what crashes the next beat /
    # freezes the trail). A poisoned INTERIOR/head point (with a finite tail) is inert here — nothing on
    # the append path reads it — and is scrubbed defensively at _simplify_escalate's entry before it can
    # reach _simplify. So we never pay an O(n) scan on the hot path (a full every-beat finite-filter of a
    # 5500-point trail measured ~565us/beat = >1 core at fleet scale — rejected). Poison is a legacy/corrupt
    # edge anyway: the schema blocks all new poison, and the trail clears to None every offroad transition.
    if not _finite_point(pt):
        return current, False
    track = list(current or [])
    if track and not _finite_point(track[-1]):
        track = [p for p in track if _finite_point(p)]
    if track and not _coarse_far(track[-1], pt, _LIVE_TRACK_MIN_MOVE_M):
        return track, False
    track.append(pt)
    # PERF — amortize the O(n^2) Douglas-Peucker. We must NOT simplify on every beat: after a simplify a
    # long/incompressible trail stays well above any low threshold, so a naive `len >= SIMPLIFY_AT` check
    # would re-run the escalation every single beat forever (a sustained fleet-wide stall). Instead we let
    # the trail accumulate raw appends up to MAX + a full SIMPLIFY_AT batch, THEN simplify back down to
    # <= MAX. Since each simplify buys at least SIMPLIFY_AT beats of headroom before the next, the O(n^2)
    # cost is paid at most once per ~SIMPLIFY_AT beats, with the stored trail bounded by MAX + SIMPLIFY_AT.
    # No per-trail state needed (it's a plain JSON list) — the bound is the trigger.
    simplify_due = len(track) >= _LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT
    return track, simplify_due


def _next_live_track(current: list | None, onroad: bool, driving: dict | None) -> list | None:
    """Pure, SYNCHRONOUS trail update (replay sim + tests): cheap append, then the simplify pass inline
    when due. The fleet heartbeat hot path uses _next_live_track_async instead, which offloads the
    O(n^2) simplify to a thread so it can't freeze the shared event loop. Storage-agnostic."""
    track, simplify_due = _append_live_point(current, onroad, driving)
    if simplify_due:
        track = _simplify_escalate(track)
    return track


async def _next_live_track_async(current: list | None, onroad: bool, driving: dict | None) -> list | None:
    """Trail update for the fleet HOT PATH (apply_heartbeat, on the single shared uvicorn loop). Same
    result as _next_live_track, but the expensive Douglas-Peucker simplify/escalation is offloaded to a
    worker thread via asyncio.to_thread (the same idiom app/storage.py uses for blocking S3 calls) so an
    adversarial/incompressible trail can stall one worker thread instead of freezing every device's
    heartbeat. _simplify_escalate is pure and owns its list, so running it off-loop is race-free; the
    read-modify-write of the stored trail already has an await window today, and last-writer-wins on a
    single point across two near-simultaneous beats for the same device is acceptable (simplify is rare
    and per-device beats are ~2s apart)."""
    track, simplify_due = _append_live_point(current, onroad, driving)
    if simplify_due:
        track = await asyncio.to_thread(_simplify_escalate, track)
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

    # New-drive detection. The trail is now PRESERVED across a transient offline (set_offline keeps
    # live_track so a cellular drop resumes the same line), so a long heartbeat gap is our signal that a
    # genuinely new drive has begun — otherwise the new drive would append to the previous drive's stale
    # trail. A gap beyond _LIVE_TRACK_NEW_DRIVE_GAP_S starts fresh; a short reconnect gap resumes.
    #
    # The gap is measured against the LAST-BEAT time from Redis, bumped every beat below — NOT the DB
    # last_heartbeat_at, which only advances on a committed beat and so lags the persist interval in
    # write-behind mode (that lag would make a healthy continuous drive look like a fresh one every
    # ~interval and collapse its trail). Fail-safe on a bad clock: a negative or absurd delta (server
    # wall-clock stepped forward) starts fresh rather than stitching a teleport onto an old trail.
    last_beat_at = None if is_new else await get_last_beat_at(redis, device.id)
    if last_beat_at is None:
        new_drive = not is_new  # no last-beat record but a row exists => treat as a new drive (fresh)
    else:
        gap = now.timestamp() - last_beat_at
        new_drive = gap < 0 or gap > _LIVE_TRACK_NEW_DRIVE_GAP_S
    # The last-beat key MUST outlive the new-drive gap window, otherwise a reconnect between
    # presence_ttl and _LIVE_TRACK_NEW_DRIVE_GAP_S would find no key (last_beat_at None -> new_drive) and
    # reset the trail — the very truncation this fix prevents, in the 30-180s window. TTL it to comfortably
    # past the gap so the gap comparison is the ONLY thing that classifies a reconnect, not key expiry.
    last_beat_ttl = int(_LIVE_TRACK_NEW_DRIVE_GAP_S) + settings.presence_ttl_seconds
    await set_last_beat_at(redis, device.id, now.timestamp(), last_beat_ttl)

    if interval > 0:
        # Write-behind: keep the working trail in Redis so a skipped commit doesn't lose accumulated
        # points. The event is built from this same fresh trail, so the map is live. TTL the trail to the
        # SAME window as the last-beat key (last_beat_ttl, 210s) — NOT presence_ttl (30s): the trail must
        # outlive the new-drive gap so a 30-180s reconnect (past presence, under the gap) can RESUME it.
        # If the trail key expired at 30s while new_drive correctly said "resume", get_live_track would
        # return None and the trail would truncate — the same reconnect-truncation bug, in write-behind
        # mode. The two keys that jointly survive a reconnect must share a lifetime.
        prior_track = None if new_drive else await get_live_track(redis, device.id)
        track = await _next_live_track_async(prior_track, payload.onroad, driving)
        await set_live_track(redis, device.id, track, last_beat_ttl)
        persisted_at = await get_persisted_at(redis, device.id)
        due = persisted_at is None or (now.timestamp() - persisted_at) >= interval
        # Force a persist on correctness boundaries: brand-new row, or an onroad transition (so the
        # durable row never sits on a stale onroad flag that other consumers / a reaper-less read see).
        should_persist = is_new or onroad_changed or due
    else:
        prior_track = None if (new_drive or status is None) else status.live_track
        track = await _next_live_track_async(prior_track, payload.onroad, driving)
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
    # Drop only the persisted-clock part of the write-behind state — NOT the trail. "Offline" is a
    # PRESENCE fact, not "the drive ended": on cellular a car drops the WS (or its presence TTL lapses)
    # many times mid-drive, and each drop lands here (device WS `finally`, and the reaper on TTL lapse).
    # Wiping live_track here truncated the live map to the reconnect point every time — the drive would
    # keep restarting from wherever the signal came back (observed: a real drive's blue line kept
    # resetting to the road it reconnected on). The trail's lifecycle is owned by the `onroad` flag
    # instead (see _append_live_point: onroad False -> trail None), and a genuinely new drive is reset in
    # apply_heartbeat on a large heartbeat gap. So a transient drop now RESUMES the same trail on
    # reconnect. See clear_persisted_at vs clear_live_state.
    await mark_offline(redis, device_id)
    await clear_persisted_at(redis, device_id)
    status = await db.get(DeviceStatus, device_id)
    if status is not None:
        status.online = False
        # An offline device cannot be onroad — clear the stale onroad flag + the live driving POSITION
        # mirror so the UI never shows the contradictory "offline but on the road" (phantom liveness).
        # But KEEP status.live_track: the accumulated route survives the drop and resumes on reconnect;
        # status_dict already clamps live_track to [] on the wire while offline, so nothing renders it in
        # the meantime, and the next heartbeat re-derives onroad from the device.
        status.onroad = False
        if status.telemetry:
            status.telemetry = {**status.telemetry, "onroad": False}
            sub = (status.telemetry.get("subsystems") or {})
            if sub.get("driving"):
                status.telemetry["subsystems"] = {**sub, "driving": None}
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
    set_offline (which clears online/onroad + the live driving POSITION mirror AND emits the
    presence:false event the client trusts). set_offline intentionally PRESERVES the accumulated
    live_track — an offline device is not necessarily a finished drive (a cellular drop mid-drive lands
    here too), and status_dict clamps live_track to [] on the wire while offline anyway, so the trail is
    invisible until the device drives again. Bounds phantom lifetime to ~TTL+interval; only scans the
    small online=True set; idempotent (a duplicate offline event is harmless — the client clamp is)."""
    while True:
        try:
            async with SessionLocal() as db:
                # Select ONLY device_id — never hydrate the full DeviceStatus rows (each carries the
                # telemetry JSON blob + the live_track, bounded at MAX + SIMPLIFY_AT points), which at thousands of online
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
