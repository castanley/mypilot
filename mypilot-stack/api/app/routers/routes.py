"""Web-facing routes (drives) & logs API (session-authenticated).

Lists, details, downloads (real bytes streamed back from object storage), deletes (DB + object
storage), and the data-retention controls. Every read/write is scoped to devices the caller owns;
deletions and retention changes leave an audit trail.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ownership, routes_service, storage
from ..audit import record_audit
from ..db import get_session
from ..deps import CurrentAuth, client_ip, get_current_user, require_admin, require_csrf
from ..models import Device, Log, LogKind, Route, RouteFile, SystemConfig, User
from ..schemas import (
    LogOut,
    Message,
    RetentionConfig,
    RetentionRunResult,
    RouteDeleteAllResult,
    RouteDetail,
    RouteFileOut,
    RouteSummary,
    RouteTrackOut,
    StorageReconcileResult,
)

router = APIRouter(prefix="/api", tags=["routes"])

RETENTION_KEY = "retention"


# --- Ownership helpers -------------------------------------------------------------------------

async def _owned_device(db: AsyncSession, user: User, device_id: str) -> Device:
    device = await db.get(Device, device_id)
    if not await ownership.owns_device(user, device, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


async def _owned_route(db: AsyncSession, user: User, route_id: str) -> Route:
    route = await db.get(Route, route_id)
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    device = await db.get(Device, route.device_id)
    if not await ownership.owns_device(user, device, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    return route


async def _owned_log(db: AsyncSession, user: User, log_id: str) -> Log:
    log = await db.get(Log, log_id)
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not found")
    device = await db.get(Device, log.device_id)
    if not await ownership.owns_device(user, device, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not found")
    return log


# --- Routes ------------------------------------------------------------------------------------

# Route columns the list/summary needs — deliberately EXCLUDES gps_track so a 500-row list never
# deserializes the (potentially tens-of-KB) polyline per route. has_track is derived cheaply from a
# NULL check on gps_track in SQL, not by loading it.
_SUMMARY_COLS = (
    Route.id, Route.device_id, Route.name, Route.alias, Route.started_at, Route.ended_at,
    Route.duration_s, Route.distance_m, Route.segment_count, Route.is_public, Route.privacy_state,
    Route.upload_status, Route.parse_status, Route.size_bytes, Route.start_lat, Route.start_lon,
    Route.created_at, Route.gps_track.isnot(None).label("has_track"),
)


def _summary_from_row(r) -> RouteSummary:
    return RouteSummary(
        id=r.id, device_id=r.device_id, name=r.name, alias=r.alias, started_at=r.started_at,
        ended_at=r.ended_at, duration_s=r.duration_s, distance_m=r.distance_m,
        segment_count=r.segment_count, is_public=r.is_public, privacy_state=r.privacy_state,
        upload_status=r.upload_status, parse_status=r.parse_status, size_bytes=r.size_bytes,
        start_lat=r.start_lat, start_lon=r.start_lon, has_track=bool(r.has_track),
        created_at=r.created_at,
    )


@router.get("/routes", response_model=list[RouteSummary])
async def list_all_routes(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    device_id: str | None = None,
    has_track: bool | None = None,
    limit: int = 500,
) -> list[RouteSummary]:
    """The caller's routes across all their devices (global collection root), with optional filters:
      ?device_id=  narrow to one owned device
      ?has_track=true  only routes with a GPS track (the drive-map overview uses this)
    Owner-scoped via a Device join (NEVER a bare select(Route) — that would leak others' routes), and
    uses the column-restricted projection so the full track array is never loaded. Mirrors the
    backups collection (GET /api/backups?device_id=). Declared BEFORE /routes/{route_id} so the
    static path isn't captured as a route id."""
    stmt = select(*_SUMMARY_COLS).join(Device, Route.device_id == Device.id).where(
        ownership.device_owner_filter(user)
    )
    if device_id is not None:
        stmt = stmt.where(Route.device_id == device_id)
    if has_track:
        stmt = stmt.where(Route.gps_track.isnot(None))
    stmt = stmt.order_by(Route.created_at.desc()).limit(min(limit, 1000))
    rows = (await db.execute(stmt)).all()
    return [_summary_from_row(r) for r in rows]


@router.get("/devices/{device_id}/routes", response_model=list[RouteSummary])
async def list_routes(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    has_track: bool | None = None,
    limit: int = 200,
) -> list[RouteSummary]:
    device = await _owned_device(db, user, device_id)
    stmt = select(*_SUMMARY_COLS).where(Route.device_id == device.id)
    if has_track:
        stmt = stmt.where(Route.gps_track.isnot(None))
    stmt = stmt.order_by(Route.created_at.desc()).limit(min(limit, 500))
    rows = (await db.execute(stmt)).all()
    return [_summary_from_row(r) for r in rows]


@router.get("/routes/{route_id}", response_model=RouteDetail)
async def get_route(
    route_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> RouteDetail:
    route = await _owned_route(db, user, route_id)
    files = (
        await db.execute(
            select(RouteFile)
            .where(RouteFile.route_id == route.id)
            .order_by(RouteFile.segment_index, RouteFile.name)
        )
    ).scalars().all()
    # Build from the summary so we never touch the (async) ``files`` relationship lazily.
    summary = RouteSummary.model_validate(route)
    summary.has_track = route.gps_track is not None  # not an ORM attr; derive it
    return RouteDetail(
        **summary.model_dump(),
        start_location=route.start_location,
        end_location=route.end_location,
        files=[RouteFileOut.model_validate(f) for f in files],
    )


@router.get("/routes/{route_id}/track", response_model=RouteTrackOut)
async def get_route_track(
    route_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> RouteTrackOut:
    """The full GPS polyline for one drive — owner-gated (404 if not the caller's), lazy-loaded by
    the per-drive map so the heavy array is only fetched when a map is actually viewed."""
    route = await _owned_route(db, user, route_id)
    return RouteTrackOut(route_id=route.id, track=route.gps_track or [])


@router.get("/routes/{route_id}/files/{file_id}/download")
async def download_route_file(
    route_id: str,
    file_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    route = await _owned_route(db, user, route_id)
    rf = await db.get(RouteFile, file_id)
    if rf is None or rf.route_id != route.id or not rf.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    try:
        data = await storage.get_object(rf.storage_key)
    except storage.ObjectNotFound:
        # The row exists but the stored bytes are gone (swept/never landed) — 404, not 500.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from None
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": storage.content_disposition(rf.name)},
    )


_VIDEO_MIME = {
    ".ts": "video/mp2t",
    ".hevc": "video/H265",   # raw HEVC — download-only; browsers can't decode it inline
    ".mp4": "video/mp4",
}


def _media_type(name: str) -> str:
    for ext, mt in _VIDEO_MIME.items():
        if name.endswith(ext):
            return mt
    return "application/octet-stream"


@router.get("/routes/{route_id}/files/{file_id}/stream")
async def stream_route_file(
    route_id: str,
    file_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Inline, Range-capable video stream (for the in-browser player / hls.js). Unlike /download
    this serves the correct video MIME, ``inline`` disposition, and honors the HTTP Range header so
    the player can seek/scrub without downloading the whole file."""
    route = await _owned_route(db, user, route_id)
    rf = await db.get(RouteFile, file_id)
    if rf is None or rf.route_id != route.id or not rf.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    key = rf.storage_key

    try:
        total = await storage.object_size(key)
    except storage.ObjectNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from None
    media = _media_type(rf.name)
    rng = request.headers.get("range")
    if rng and rng.startswith("bytes="):
        spec = rng.split("=", 1)[1].split(",", 1)[0].strip()
        lo_s, _, hi_s = spec.partition("-")
        try:
            start = int(lo_s) if lo_s else 0
            end = int(hi_s) if hi_s else total - 1
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Bad Range")
        start = max(0, start)
        end = min(end, total - 1)
        if start > end:
            return Response(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                            headers={"Content-Range": f"bytes */{total}"})
        data = await storage.get_range(key, start, end)
        return Response(
            content=data, status_code=status.HTTP_206_PARTIAL_CONTENT, media_type=media,
            headers={
                "Content-Range": f"bytes {start}-{end}/{total}",
                "Accept-Ranges": "bytes",
                "Content-Disposition": f'inline; filename="{rf.name}"',
                "Cache-Control": "private, max-age=3600",
            },
        )
    data = await storage.get_object(key)
    return Response(
        content=data, media_type=media,
        headers={"Accept-Ranges": "bytes", "Content-Disposition": f'inline; filename="{rf.name}"',
                 "Cache-Control": "private, max-age=3600"},
    )


@router.get("/routes/{route_id}/playlist.m3u8")
async def route_hls_playlist(
    route_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Synthetic HLS manifest stitching a drive's per-segment qcamera.ts into one playable stream
    (hls.js / Safari). Each segment is ~60s; we point #EXTINF at the per-file /stream endpoint."""
    route = await _owned_route(db, user, route_id)
    files = (
        await db.execute(
            select(RouteFile)
            .where(RouteFile.route_id == route.id, RouteFile.kind == "qcamera",
                   RouteFile.uploaded.is_(True))
            .order_by(RouteFile.segment_index)
        )
    ).scalars().all()
    if not files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No playable video")

    SEG = 60.0  # comma segments are 60s; last one may be shorter but HLS tolerates this
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", f"#EXT-X-TARGETDURATION:{int(SEG)}",
             "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-PLAYLIST-TYPE:VOD"]
    for f in files:
        lines.append(f"#EXTINF:{SEG:.3f},")
        lines.append(f"files/{f.id}/stream")
    lines.append("#EXT-X-ENDLIST")
    return Response(
        content="\n".join(lines) + "\n",
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "private, max-age=60"},
    )


@router.delete("/routes/{route_id}", response_model=Message)
async def delete_route(
    route_id: str,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Message:
    route = await _owned_route(db, auth.user, route_id)
    device_id = route.device_id
    name = route.name
    await routes_service.delete_route(db, route)
    await record_audit(
        db,
        action="route.delete",
        actor_type="user",
        actor_id=str(auth.user.id),
        device_id=device_id,
        metadata={"route_id": route_id, "name": name},
        ip=client_ip(request),
    )
    await db.commit()
    return Message(detail="Route deleted")


@router.delete("/routes", response_model=RouteDeleteAllResult)
async def delete_all_routes(
    request: Request,
    device_id: str | None = None,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> RouteDeleteAllResult:
    """Bulk-delete all of the user's routes (DB + stored bytes), optionally scoped to one device.
    When device_id is given, it's ownership-checked first."""
    if device_id is not None:
        await _owned_device(db, auth.user, device_id)  # 404/403 if not the user's device
    count = await routes_service.delete_all_routes(db, auth.user.id, device_id)
    await record_audit(
        db,
        action="route.delete_all",
        actor_type="user",
        actor_id=str(auth.user.id),
        device_id=device_id,
        metadata={"routes_deleted": count, "scope": device_id or "all"},
        ip=client_ip(request),
    )
    await db.commit()
    return RouteDeleteAllResult(routes_deleted=count)


# --- Logs --------------------------------------------------------------------------------------

@router.get("/devices/{device_id}/logs", response_model=list[LogOut])
async def list_logs(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    kind: str | None = None,
    limit: int = 200,
) -> list[LogOut]:
    device = await _owned_device(db, user, device_id)
    stmt = select(Log).where(Log.device_id == device.id)
    if kind:
        stmt = stmt.where(Log.kind == kind)
    stmt = stmt.order_by(Log.created_at.desc()).limit(min(limit, 500))
    rows = (await db.execute(stmt)).scalars().all()
    return [LogOut.model_validate(r) for r in rows]


@router.get("/logs/{log_id}", response_model=LogOut)
async def get_log(
    log_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> LogOut:
    log = await _owned_log(db, user, log_id)
    return LogOut.model_validate(log)


@router.get("/logs/{log_id}/download")
async def download_log(
    log_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    log = await _owned_log(db, user, log_id)
    if not log.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not uploaded")
    try:
        data = await storage.get_object(log.storage_key)
    except storage.ObjectNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not found") from None
    media = "text/plain" if log.kind == LogKind.CRASH else "application/octet-stream"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": storage.content_disposition(log.name)},
    )


@router.delete("/logs/{log_id}", response_model=Message)
async def delete_log(
    log_id: str,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Message:
    log = await _owned_log(db, auth.user, log_id)
    device_id = log.device_id
    name = log.name
    await routes_service.delete_log(db, log)
    await record_audit(
        db,
        action="log.delete",
        actor_type="user",
        actor_id=str(auth.user.id),
        device_id=device_id,
        metadata={"log_id": log_id, "name": name},
        ip=client_ip(request),
    )
    await db.commit()
    return Message(detail="Log deleted")


# --- Retention ---------------------------------------------------------------------------------

async def _get_retention(db: AsyncSession) -> RetentionConfig:
    """Read the stored retention config. Back-compat: an old config has only `days`, which we map
    onto both categories; a newer one has route_days/log_days."""
    cfg = await db.get(SystemConfig, RETENTION_KEY)
    if cfg is not None and isinstance(cfg.value, dict):
        v = cfg.value
        days = int(v.get("days", 0))
        return RetentionConfig(
            days=days,
            route_days=int(v["route_days"]) if v.get("route_days") is not None else days,
            log_days=int(v["log_days"]) if v.get("log_days") is not None else days,
        )
    return RetentionConfig(days=0, route_days=0, log_days=0)


@router.get("/retention", response_model=RetentionConfig)
async def get_retention(
    _auth: CurrentAuth = Depends(require_admin),  # global platform setting — admin-only (write already is)
    db: AsyncSession = Depends(get_session),
) -> RetentionConfig:
    return await _get_retention(db)


@router.put("/retention", response_model=RetentionConfig)
async def set_retention(
    payload: RetentionConfig,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> RetentionConfig:
    if not auth.user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    route_days, log_days = payload.resolved()
    stored = {"days": payload.days, "route_days": route_days, "log_days": log_days}
    cfg = await db.get(SystemConfig, RETENTION_KEY)
    if cfg is None:
        db.add(SystemConfig(key=RETENTION_KEY, value=stored))
    else:
        cfg.value = stored
    await record_audit(
        db,
        action="retention.configure",
        actor_type="user",
        actor_id=str(auth.user.id),
        metadata=stored,
        ip=client_ip(request),
    )
    await db.commit()
    return RetentionConfig(days=payload.days, route_days=route_days, log_days=log_days)


@router.post("/retention/run", response_model=RetentionRunResult)
async def run_retention_now(
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> RetentionRunResult:
    if not auth.user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    route_days, log_days = (await _get_retention(db)).resolved()
    if route_days <= 0 and log_days <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Retention is disabled (set a non-zero number of days for routes and/or logs first)",
        )
    routes_deleted, logs_deleted = await routes_service.run_retention(db, route_days, log_days)
    await record_audit(
        db,
        action="retention.run",
        actor_type="user",
        actor_id=str(auth.user.id),
        metadata={"route_days": route_days, "log_days": log_days,
                  "routes_deleted": routes_deleted, "logs_deleted": logs_deleted},
        ip=client_ip(request),
    )
    await db.commit()
    return RetentionRunResult(routes_deleted=routes_deleted, logs_deleted=logs_deleted,
                              route_days=route_days, log_days=log_days)


@router.post("/maintenance/reconcile-storage", response_model=StorageReconcileResult)
async def reconcile_storage(
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> StorageReconcileResult:
    """Admin maintenance: mark route files / logs whose stored object is gone as not-uploaded, so the
    UI stops offering a download that would 404. Non-destructive — route metadata + GPS are kept."""
    if not auth.user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    result = await routes_service.reconcile_storage(db)
    await record_audit(
        db,
        action="storage.reconcile",
        actor_type="user",
        actor_id=str(auth.user.id),
        metadata=result,
        ip=client_ip(request),
    )
    await db.commit()
    return StorageReconcileResult(**result)
