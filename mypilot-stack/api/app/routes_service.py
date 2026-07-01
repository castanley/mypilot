"""Shared logic for routes/logs: storage keys, deletion (DB + MinIO), retention, metadata derivation."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import geocode, storage
from .models import Device, Log, Route, RouteFile

_EARTH_M = 6_371_000.0


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = math.pi / 180.0
    dlat = (lat2 - lat1) * r
    dlon = (lon2 - lon1) * r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1 * r) * math.cos(lat2 * r) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_M * math.asin(math.sqrt(min(1.0, a)))


def route_metrics(gps_track, segment_count: int = 0) -> tuple[int | None, float | None]:
    """Derive (duration_s, distance_m) from a route's stored GPS polyline — the same
    ``[t, lat, lon]`` shape the ingest path stores (t = seconds since drive start). No qlog needed.

    duration_s = the last point's t (rounded), falling back to segment_count*60 when the track is
    too short to have a meaningful span. distance_m = the sum of great-circle hops between
    consecutive fixes. Returns (None, None) for an absent/degenerate track so callers can leave the
    columns null rather than store a bogus 0. Bad/short points are skipped defensively (a stray
    non-numeric or out-of-range fix never aborts the whole computation)."""
    _SEG_S = 60.0
    pts: list[tuple[float, float, float]] = []
    for p in gps_track or []:
        if not isinstance(p, (list, tuple)) or len(p) < 3:
            continue
        try:
            t, lat, lon = float(p[0]), float(p[1]), float(p[2])
        except (TypeError, ValueError):
            continue
        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
            pts.append((t, lat, lon))

    if len(pts) < 2:
        # No usable track: fall back to the segment count for duration; distance is unknowable.
        dur = int(round(segment_count * _SEG_S)) if segment_count else None
        return (dur or None), None

    duration = int(round(pts[-1][0]))
    if duration <= 0 and segment_count:
        duration = int(round(segment_count * _SEG_S))
    distance = 0.0
    for (_, la1, lo1), (_, la2, lo2) in zip(pts, pts[1:]):
        distance += _haversine_m(la1, lo1, la2, lo2)
    return (duration or None), round(distance, 1)


# Object-key builders — where a route/log's artifacts live in object storage.
def route_prefix(device_id: str, route_id: str) -> str:
    return f"routes/{device_id}/{route_id}/"


def route_file_key(device_id: str, route_id: str, segment_index: int, name: str) -> str:
    return f"routes/{device_id}/{route_id}/{segment_index}/{name}"


def log_key(device_id: str, log_id: str, name: str) -> str:
    return f"logs/{device_id}/{log_id}/{name}"


async def delete_route(db: AsyncSession, route: Route) -> None:
    # Delete each file by its exact stored key (correct even if a fork stored non-default keys); fall
    # back to a prefix sweep only if no file row carries a key.
    files = (
        await db.execute(select(RouteFile).where(RouteFile.route_id == route.id))
    ).scalars().all()
    keys = [f.storage_key for f in files if f.storage_key]
    try:
        if keys:
            for key in keys:
                await storage.delete_object(key)
        else:
            await storage.delete_prefix(route_prefix(route.device_id, route.id))
    except Exception:  # noqa: BLE001 - object may not exist; remove the record regardless
        pass
    await db.delete(route)


async def delete_log(db: AsyncSession, log: Log) -> None:
    if log.storage_key:
        try:
            await storage.delete_object(log.storage_key)
        except Exception:  # noqa: BLE001
            pass
    await db.delete(log)


async def delete_all_routes(
    db: AsyncSession, owner_id: int, device_id: str | None = None
) -> int:
    """Delete all of one owner's routes (DB + MinIO), optionally scoped to a single device. Always
    owner-scoped via the device join so one user can't wipe another's routes. Returns the count."""
    stmt = select(Route).join(Device, Route.device_id == Device.id).where(Device.owner_id == owner_id)
    if device_id is not None:
        stmt = stmt.where(Route.device_id == device_id)
    routes = (await db.execute(stmt)).scalars().all()
    for r in routes:
        await delete_route(db, r)
    await db.commit()
    return len(routes)


async def run_retention(db: AsyncSession, route_days: int, log_days: int | None = None) -> tuple[int, int]:
    """Delete routes older than ``route_days`` and logs older than ``log_days`` (per-category).
    A category's <=0 value keeps that category forever. ``log_days=None`` reuses ``route_days``
    (back-compat with the old single-knob signature). Returns (routes_deleted, logs_deleted)."""
    if log_days is None:
        log_days = route_days
    now = datetime.now(timezone.utc)

    routes_deleted = 0
    if route_days > 0:
        cutoff = now - timedelta(days=route_days)
        routes = (await db.execute(select(Route).where(Route.created_at < cutoff))).scalars().all()
        for r in routes:
            await delete_route(db, r)
        routes_deleted = len(routes)

    logs_deleted = 0
    if log_days > 0:
        cutoff = now - timedelta(days=log_days)
        logs = (await db.execute(select(Log).where(Log.created_at < cutoff))).scalars().all()
        for log in logs:
            await delete_log(db, log)
        logs_deleted = len(logs)

    await db.commit()
    return (routes_deleted, logs_deleted)


async def reconcile_storage(db: AsyncSession) -> dict:
    """Find route files / logs whose row claims an upload but whose object is gone from storage
    (swept, or an upload that never landed) and mark them not-uploaded. NON-DESTRUCTIVE: the row and
    its route's metadata/GPS are kept; we only clear the `uploaded` flag (and a route file's stale
    `storage_key`) so the UI stops offering a download that would 404. Returns the counts touched.

    Idempotent — re-running only re-flags newly-orphaned rows. Files are checked by HEAD; reads run in
    a worker thread, so this is O(files) network calls (run it in a maintenance window for large sets).
    """
    route_files_reconciled = 0
    files = (
        await db.execute(select(RouteFile).where(RouteFile.uploaded.is_(True),
                                                 RouteFile.storage_key.is_not(None)))
    ).scalars().all()
    for f in files:
        if not await storage.object_exists(f.storage_key):
            f.uploaded = False
            f.storage_key = None
            route_files_reconciled += 1

    logs_reconciled = 0
    logs = (
        await db.execute(select(Log).where(Log.storage_key.is_not(None)))
    ).scalars().all()
    for log in logs:
        if not await storage.object_exists(log.storage_key):
            log.storage_key = None
            logs_reconciled += 1

    await db.commit()
    return {"route_files_reconciled": route_files_reconciled, "logs_reconciled": logs_reconciled}


def _track_endpoints(gps_track) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    """First and last valid (lat, lon) of a ``[t, lat, lon]`` track, for start/end geocoding."""
    pts: list[tuple[float, float]] = []
    for p in gps_track or []:
        if not isinstance(p, (list, tuple)) or len(p) < 3:
            continue
        try:
            lat, lon = float(p[1]), float(p[2])
        except (TypeError, ValueError):
            continue
        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
            pts.append((lat, lon))
    if not pts:
        return None, None
    return pts[0], pts[-1]


def fill_route_metadata(route: Route) -> bool:
    """Fill a route's derived metadata (duration_s, distance_m, start/end city location) from its
    already-stored GPS track — ONLY where the field is currently null, so a device-supplied value is
    never overwritten. Pure + offline (metrics = haversine/last-t; city = the bundled offline dataset,
    no outbound). Returns True if anything changed. Used by both route_complete (going-forward) and the
    backfill (existing routes), so the two paths derive identically."""
    changed = False

    if route.duration_s is None or route.distance_m is None:
        dur, dist = route_metrics(route.gps_track, route.segment_count)
        if route.duration_s is None and dur is not None:
            route.duration_s = dur
            changed = True
        if route.distance_m is None and dist is not None:
            route.distance_m = dist
            changed = True

    if route.start_location is None or route.end_location is None:
        start_pt, end_pt = _track_endpoints(route.gps_track)
        if route.start_location is None and start_pt is not None:
            city = geocode.nearest_city(start_pt[0], start_pt[1])
            if city is not None:
                route.start_location = city
                changed = True
        if route.end_location is None and end_pt is not None:
            city = geocode.nearest_city(end_pt[0], end_pt[1])
            if city is not None:
                route.end_location = city
                changed = True

    return changed


async def backfill_route_metrics(db: AsyncSession) -> dict:
    """Populate duration_s/distance_m + start/end city on existing routes that are missing them,
    derived from each route's already-stored GPS track (see fill_route_metadata). METADATA-ONLY +
    REVERSIBLE: reads gps_track, writes only those scalar/text columns; touches no object storage and
    no other field. Fully recomputable, so re-running is idempotent (a fully-populated route is a
    no-op). Offline (bundled city dataset) — no network — so cheap even over the whole table. Only
    fills a column that is currently NULL, so a device-supplied value is never clobbered."""
    updated = 0
    skipped_no_source = 0
    routes = (
        await db.execute(
            select(Route).where(
                (Route.duration_s.is_(None))
                | (Route.distance_m.is_(None))
                | (Route.start_location.is_(None))
                | (Route.end_location.is_(None))
            )
        )
    ).scalars().all()
    for route in routes:
        if fill_route_metadata(route):
            updated += 1
        elif route.gps_track is None and not route.segment_count:
            skipped_no_source += 1

    await db.commit()
    return {"routes_updated": updated, "routes_skipped_no_source": skipped_no_source}
