"""Shared logic for routes/logs: storage keys, deletion (DB + MinIO), retention."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import storage
from .models import Device, Log, Route, RouteFile


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
