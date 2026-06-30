"""Device-facing self-report endpoints. Authenticated by Ed25519 request signatures.

These are the REST equivalents of the realtime WebSocket frames, kept available as a resilient
fallback (and for testing device auth without a live socket)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import storage
from ..db import get_session
from ..deps import get_authenticated_device
from ..device_service import apply_heartbeat, record_command_result, status_dict
from ..models import Device, Model
from ..redis_client import get_redis
from ..schemas import (
    CommandResultRequest,
    DeviceStatusOut,
    HeartbeatRequest,
    Message,
    SettingResultRequest,
    SettingsSyncRequest,
)
from ..settings_service import apply_settings_sync, record_setting_result

router = APIRouter(prefix="/api/devices/self", tags=["device"])


@router.post("/heartbeat", response_model=DeviceStatusOut)
async def heartbeat(
    payload: HeartbeatRequest,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> DeviceStatusOut:
    status_row = await apply_heartbeat(db, redis, device, payload)
    # The device just heartbeated, so it is online by definition — the serializer clamps to that.
    return DeviceStatusOut.model_validate(status_dict(status_row, online=True))


@router.post("/commands/{command_id}/result", response_model=Message)
async def command_result(
    command_id: str,
    payload: CommandResultRequest,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Message:
    result = await record_command_result(db, redis, device, command_id, payload.ok, payload.detail)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown command")
    return Message(detail="recorded")


@router.post("/settings/sync", response_model=Message)
async def settings_sync(
    payload: SettingsSyncRequest,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_session),
) -> Message:
    await apply_settings_sync(db, device, payload.capabilities, payload.values)
    return Message(detail="synced")


@router.post("/settings/result", response_model=Message)
async def setting_result(
    payload: SettingResultRequest,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Message:
    res = await record_setting_result(
        db, redis, device, payload.change_id, payload.ok, payload.value, payload.detail
    )
    if res is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown change")
    return Message(detail="recorded")


@router.get("/models/{model_key}/download")
async def download_model(
    model_key: str,
    device: Device = Depends(get_authenticated_device),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Stream a model artifact to the device so it can verify the sha256 before activating."""
    model = (
        await db.execute(select(Model).where(Model.key == model_key))
    ).scalar_one_or_none()
    if model is None or not model.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown model")
    data = await storage.get_object(model.storage_key)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"X-MyPilot-Checksum": model.checksum},
    )
