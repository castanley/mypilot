"""Device-facing ingest endpoints for routes (drives) and logs.

Authenticated by Ed25519 request signatures (same as the other device-self endpoints). The
device declares a route, uploads each segment file as raw bytes (stored verbatim in object
storage), then marks the upload complete. Logs follow the same declare-then-upload shape.

Nothing here touches driving behavior — it only moves already-recorded artifacts off the device.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import routes_service, storage
from ..config import get_settings
from ..db import get_session
from ..deps import get_authenticated_device
from ..models import (
    Device,
    Log,
    LogKind,
    Route,
    RouteFile,
    Upload,
    UploadStatus,
)
from ..redis_client import get_redis, publish_event
from ..schemas import (
    LogOut,
    LogStartRequest,
    Message,
    RouteStartRequest,
    RouteStartResponse,
)

settings = get_settings()

router = APIRouter(prefix="/api/ingest", tags=["ingest"])

# Per-file size ceiling (config-driven). The body is fully buffered in RAM (it's signature-verified
# whole), so this + the Content-Length precheck in get_authenticated_device bound peak memory. The
# precheck rejects before buffering; this is the post-read backstop for chunked/unknown-length bodies.
MAX_FILE_BYTES = settings.max_upload_bytes

# Bound how many uploads buffer concurrently in this process. Post-drive bursts (many cars come
# offroad together, each flushing several segments) could otherwise hold dozens of multi-MB bodies
# resident at once and OOM the worker — which also holds every live WebSocket (a total outage). A
# semaphore caps concurrency; excess uploads await a slot instead of all allocating at once.
_upload_slots = asyncio.Semaphore(settings.max_concurrent_uploads)

# Map a recorded filename to a RouteFile.kind when the device didn't declare it.
def _kind_for(name: str) -> str:
    n = name.lower()
    if n.startswith("qcamera"):
        return "qcamera"
    if n.startswith("fcamera"):
        return "fcamera"
    if n.startswith("ecamera"):
        return "ecamera"
    if n.startswith("dcamera"):
        return "dcamera"
    if n.startswith("rlog"):
        return "rlog"
    return "qlog"


_CONTENT_TYPE = {
    "qcamera": "video/mp2t",
    "fcamera": "video/H265",
    "ecamera": "video/H265",
    "dcamera": "video/H265",
}


def _apply_track(route: Route, track: list[list[float]] | None) -> None:
    """Store a sanitized GPS polyline on the route + scalar start point for the overview marker.
    Each point is [t, lat, lon] — t = seconds since drive start, used to sync a marker to video
    playback on the drive page (the map gallery just ignores t and draws lat/lon). Keeps only
    well-formed in-range points; no-op on empty/garbage so a GPS-less drive simply has no line.

    A track only ever GROWS: a drive is uploaded across several offroad cycles, and an early cycle
    can extract a partial (e.g. first-segment-only) track before the rest of the segments are ready.
    We must never let that shorter track overwrite a fuller one already stored — the bug where most
    trips showed a track truncated at the first 60s segment. So we replace only when the incoming
    track has MORE points than what's stored."""
    if not track:
        return
    clean: list[list[float]] = []
    for pt in track:
        if not isinstance(pt, (list, tuple)) or len(pt) < 3:
            continue
        try:
            t, lat, lon = float(pt[0]), float(pt[1]), float(pt[2])
        except (TypeError, ValueError):
            continue
        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and not (lat == 0.0 and lon == 0.0):
            clean.append([round(t, 1), round(lat, 5), round(lon, 5)])
    if len(clean) <= len(route.gps_track or []):
        return  # never shrink/replace-with-equal an existing track
    route.gps_track = clean
    route.start_lat, route.start_lon = clean[0][1], clean[0][2]


# --- Routes ------------------------------------------------------------------------------------

@router.post("/routes/start", response_model=RouteStartResponse, status_code=status.HTTP_201_CREATED)
async def route_start(
    payload: RouteStartRequest,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_session),
) -> RouteStartResponse:
    # Idempotent on (device, route name): re-declaring an existing route reuses it.
    existing = (
        await db.execute(
            select(Route).where(Route.device_id == device.id, Route.name == payload.name)
        )
    ).scalar_one_or_none()
    if existing is not None:
        route = existing
        # The agent re-declares a route across upload cycles. Adopt the incoming track whenever it's
        # FULLER than what we have — an early cycle may have stored a partial (first-segment) track,
        # and a later cycle carries the complete drive. _apply_track only grows, never shrinks.
        _apply_track(route, payload.track)
    else:
        route = Route(
            device_id=device.id,
            name=payload.name,
            alias=payload.alias,
            started_at=payload.started_at,
            ended_at=payload.ended_at,
            duration_s=payload.duration_s,
            distance_m=payload.distance_m,
            segment_count=payload.segment_count or len(payload.files),
            privacy_state=payload.privacy_state,
            start_location=payload.start_location,
            end_location=payload.end_location,
            upload_status=UploadStatus.UPLOADING,
        )
        _apply_track(route, payload.track)
        db.add(route)
        await db.flush()  # assign route.id
        for decl in payload.files:
            db.add(
                RouteFile(
                    route_id=route.id,
                    segment_index=decl.segment_index,
                    name=decl.name,
                    kind=decl.kind,
                )
            )

    upload = Upload(device_id=device.id, kind="route", target_id=route.id, status="open")
    db.add(upload)
    await db.commit()
    return RouteStartResponse(
        upload_id=upload.id, route_id=route.id, track_points=len(route.gps_track or [])
    )


@router.put("/routes/{route_id}/files/{segment_index}/{name}", response_model=Message)
async def route_file_upload(
    route_id: str,
    segment_index: int,
    name: str,
    request: Request,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_session),
) -> Message:
    route = await db.get(Route, route_id)
    if route is None or route.device_id != device.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown route")

    body = await request.body()  # already buffered + signature-verified by the auth dependency
    if len(body) > MAX_FILE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")

    rf = (
        await db.execute(
            select(RouteFile).where(
                RouteFile.route_id == route.id,
                RouteFile.segment_index == segment_index,
                RouteFile.name == name,
            )
        )
    ).scalar_one_or_none()
    if rf is None:
        # Allow upload of an undeclared file (device may add segments after start).
        rf = RouteFile(route_id=route.id, segment_index=segment_index, name=name, kind=_kind_for(name))
        db.add(rf)

    key = routes_service.route_file_key(device.id, route.id, segment_index, name)
    async with _upload_slots:  # bound concurrent in-RAM uploads (cap peak memory)
        await storage.put_object(key, body, _CONTENT_TYPE.get(rf.kind, "application/octet-stream"))
    rf.storage_key = key
    rf.size_bytes = len(body)
    rf.uploaded = True
    await db.commit()
    return Message(detail="stored")


@router.post("/routes/{route_id}/complete", response_model=Message)
async def route_complete(
    route_id: str,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Message:
    route = await db.get(Route, route_id)
    if route is None or route.device_id != device.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown route")

    files = (
        await db.execute(select(RouteFile).where(RouteFile.route_id == route.id))
    ).scalars().all()
    route.size_bytes = sum(f.size_bytes for f in files if f.uploaded)
    route.segment_count = len({f.segment_index for f in files}) or route.segment_count
    route.upload_status = UploadStatus.COMPLETE
    route.parse_status = "parsed"

    # Derive duration/distance + start/end city from the stored GPS track (the device doesn't send
    # them). Only fill when missing, so a value the device DID provide is never overwritten. Bus-free,
    # no qlog read, no outbound (city via the bundled offline dataset).
    routes_service.fill_route_metadata(route)

    for upload in (
        await db.execute(
            select(Upload).where(Upload.target_id == route.id, Upload.status == "open")
        )
    ).scalars():
        upload.status = "complete"
        upload.completed_at = datetime.now(timezone.utc)

    await db.commit()
    await publish_event(
        redis,
        {"type": "device_event", "device_id": device.id, "event": "route_uploaded", "route_id": route.id},
    )
    return Message(detail="completed")


# --- Logs --------------------------------------------------------------------------------------

@router.post("/logs/start", response_model=LogOut, status_code=status.HTTP_201_CREATED)
async def log_start(
    payload: LogStartRequest,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_session),
) -> LogOut:
    kind = payload.kind if payload.kind in vars(LogKind).values() else LogKind.SYSTEM
    log = Log(
        device_id=device.id,
        kind=kind,
        name=payload.name,
        route_name=payload.route_name,
        upload_status=UploadStatus.UPLOADING,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return LogOut.model_validate(log)


@router.put("/logs/{log_id}/content", response_model=Message)
async def log_upload(
    log_id: str,
    request: Request,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Message:
    log = await db.get(Log, log_id)
    if log is None or log.device_id != device.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown log")

    body = await request.body()
    if len(body) > MAX_FILE_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Log too large")

    key = routes_service.log_key(device.id, log.id, log.name)
    async with _upload_slots:
        await storage.put_object(key, body, "text/plain" if log.kind == LogKind.CRASH else "application/octet-stream")
    log.storage_key = key
    log.size_bytes = len(body)
    log.upload_status = UploadStatus.COMPLETE
    await db.commit()
    await publish_event(
        redis,
        {"type": "device_event", "device_id": device.id, "event": "log_uploaded", "log_id": log.id},
    )
    return Message(detail="stored")
