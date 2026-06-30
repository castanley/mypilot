"""Driving-model catalog + per-device active model, switch, and rollback (M5)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ownership
from ..db import get_session
from ..deps import CurrentAuth, client_ip, get_current_user, require_csrf
from ..models import Device, DeviceStatus, DeviceStatusValue, Model, User
from ..models_service import build_device_models, issue_model_switch
from ..schemas import (
    CommandOut,
    DeviceModelsResponse,
    ModelOut,
    ModelSwitchRequest,
)

router = APIRouter(prefix="/api", tags=["models"])


async def _owned(db: AsyncSession, user: User, device_id: str) -> Device:
    device = await db.get(Device, device_id)
    if not await ownership.owns_device(user, device, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


async def _onroad(db: AsyncSession, device_id: str) -> bool:
    row = await db.get(DeviceStatus, device_id)
    return bool(row.onroad) if row else False


@router.get("/models", response_model=list[ModelOut])
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[ModelOut]:
    rows = (
        await db.execute(select(Model).order_by(Model.is_default.desc(), Model.name))
    ).scalars().all()
    return [ModelOut.model_validate(m) for m in rows]


@router.get("/devices/{device_id}/models", response_model=DeviceModelsResponse)
async def device_models(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> DeviceModelsResponse:
    device = await _owned(db, user, device_id)
    return await build_device_models(db, device, await _onroad(db, device_id))


@router.post(
    "/devices/{device_id}/models/switch",
    response_model=CommandOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def switch_model(
    device_id: str,
    payload: ModelSwitchRequest,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> CommandOut:
    device = await _owned(db, auth.user, device_id)
    if device.status != DeviceStatusValue.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device is not active")
    command = await issue_model_switch(
        db,
        request.app.state.manager,
        auth.user.id,
        device,
        payload.model_key,
        payload.confirm,
        client_ip(request),
    )
    return CommandOut.model_validate(command)


@router.post(
    "/devices/{device_id}/models/rollback",
    response_model=CommandOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rollback_model(
    device_id: str,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> CommandOut:
    device = await _owned(db, auth.user, device_id)
    if not device.previous_model_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No previous model to roll back to"
        )
    command = await issue_model_switch(
        db,
        request.app.state.manager,
        auth.user.id,
        device,
        device.previous_model_key,
        confirm=True,
        ip=client_ip(request),
        is_rollback=True,
    )
    return CommandOut.model_validate(command)
