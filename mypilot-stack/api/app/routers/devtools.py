"""Admin-only developer tools: create / list / delete SIMULATED test devices, and replay a recorded
drive through one so live telemetry (speed/heading/position) can be exercised without driving.

Hard safety invariant: every mutation here is gated to the caller's OWN devices AND to
``is_simulated == True``. A real, paired device can never be created, mutated, replayed, or deleted
through this surface. All endpoints are admin-only (require_admin / require_admin_csrf) and audited.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_audit
from ..deps import CurrentAuth, client_ip, get_session, require_admin, require_admin_csrf
from ..models import Device, DeviceStatus, DeviceStatusValue, Route
from ..redis_client import get_redis, online_among
from ..replay_service import start_replay, stop_replay
from ..schemas import DeviceSummary
from .devices import _to_summary

router = APIRouter(prefix="/api/admin/dev", tags=["devtools"])

# A stable hardware_id prefix marks the lineage of dev-created sim devices (purely informational;
# the authoritative marker is the is_simulated column).
SIM_HARDWARE_PREFIX = "SIM-"


class SimDeviceCreate(BaseModel):
    alias: str = Field(default="Simulated test device", min_length=1, max_length=128)
    platform: str | None = Field(default="SIMULATED RAM 2500", max_length=128)


class ReplayRequest(BaseModel):
    route_id: str
    # >1 = faster than real time (default 4x so a long drive is watchable quickly); clamped server-side.
    speed_factor: float = Field(default=4.0, ge=0.25, le=60.0)


async def _owned_sim(db: AsyncSession, user_id: int, device_id: str) -> Device:
    """Fetch a device that the caller owns AND that is simulated — else 404. This is the guard that
    makes it impossible to touch a real device through the dev tools."""
    device = await db.get(Device, device_id)
    if device is None or device.owner_id != user_id or not device.is_simulated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulated device not found")
    return device


@router.get("/sim-devices", response_model=list[DeviceSummary])
async def list_sim_devices(
    auth: CurrentAuth = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
) -> list[DeviceSummary]:
    devices = (
        await db.execute(
            select(Device).where(Device.owner_id == auth.user.id, Device.is_simulated.is_(True))
        )
    ).scalars().all()
    ids = [d.id for d in devices]
    statuses = {
        s.device_id: s
        for s in (
            await db.execute(select(DeviceStatus).where(DeviceStatus.device_id.in_(ids)))
        ).scalars()
    } if ids else {}
    online = await online_among(redis, ids)
    return [_to_summary(d, statuses.get(d.id), d.id in online) for d in devices]


@router.post("/sim-devices", response_model=DeviceSummary, status_code=status.HTTP_201_CREATED)
async def create_sim_device(
    payload: SimDeviceCreate,
    request: Request,
    auth: CurrentAuth = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> DeviceSummary:
    # A sim device is immediately ACTIVE (no pairing handshake) and owned by the admin. It has no
    # DeviceKey, so it can never authenticate as a real device on the device WebSocket/ingest paths.
    device = Device(
        owner_id=auth.user.id,
        alias=payload.alias,
        hardware_id=f"{SIM_HARDWARE_PREFIX}{auth.user.id}",
        status=DeviceStatusValue.ACTIVE,
        platform=payload.platform,
        software_version="0.0.0-sim",
        branch="sim",
        is_simulated=True,
    )
    db.add(device)
    await db.flush()  # assign id
    db.add(DeviceStatus(device_id=device.id, online=False, onroad=False))
    await record_audit(
        db, action="admin.dev.sim_device.create", actor_type="user", actor_id=str(auth.user.id),
        device_id=device.id, metadata={"alias": payload.alias}, ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(device)
    return _to_summary(device, None, online=False)


@router.delete("/sim-devices/{device_id}")
async def delete_sim_device(
    device_id: str,
    request: Request,
    auth: CurrentAuth = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    device = await _owned_sim(db, auth.user.id, device_id)  # sim-only guard
    await stop_replay(device.id)  # cancel any in-flight replay before removing the row
    await record_audit(
        db, action="admin.dev.sim_device.delete", actor_type="user", actor_id=str(auth.user.id),
        device_id=device.id, metadata={"alias": device.alias}, ip=client_ip(request),
    )
    await db.delete(device)  # cascade drops its status row + any keys (it has none)
    await db.commit()
    return {"message": "Simulated device removed"}


@router.post("/sim-devices/{device_id}/replay")
async def replay_drive(
    device_id: str,
    payload: ReplayRequest,
    request: Request,
    auth: CurrentAuth = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
    redis=Depends(get_redis),
) -> dict:
    """Replay a recorded route's GPS track through this SIMULATED device as live telemetry. Sim-only
    target; the route must be owned by the caller and have a stored track."""
    device = await _owned_sim(db, auth.user.id, device_id)  # sim-only guard

    route = await db.get(Route, payload.route_id)
    if route is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    route_owner = await db.get(Device, route.device_id)
    if route_owner is None or route_owner.owner_id != auth.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
    track = route.gps_track or []
    if len(track) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Route has no GPS track to replay"
        )

    await start_replay(redis, device.id, track, speed_factor=payload.speed_factor)
    await record_audit(
        db, action="admin.dev.sim_device.replay", actor_type="user", actor_id=str(auth.user.id),
        device_id=device.id,
        metadata={"route_id": route.id, "points": len(track), "speed_factor": payload.speed_factor},
        ip=client_ip(request),
    )
    await db.commit()
    return {"message": "Replay started", "points": len(track)}


@router.post("/sim-devices/{device_id}/replay/stop")
async def replay_stop(
    device_id: str,
    auth: CurrentAuth = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> dict:
    device = await _owned_sim(db, auth.user.id, device_id)  # sim-only guard
    stopped = await stop_replay(device.id)
    return {"message": "Replay stopped" if stopped else "No replay running", "stopped": stopped}
