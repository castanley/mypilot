"""Device settings: list (definitions + values), change (gated + audited), reset-to-default."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from mypilot_protocol.messages import FrameType
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from .. import ownership
from ..audit import record_audit
from ..db import get_session
from ..deps import CurrentAuth, client_ip, get_current_user, require_csrf
from ..models import (
    DangerLevel,
    Device,
    DeviceSetting,
    DeviceStatus,
    DeviceStatusValue,
    SettingChange,
    SettingChangeStatus,
    SettingDefinition,
    User,
)
from ..redis_client import get_redis
from ..schemas import SettingChangeOut, SettingChangeRequest, SettingsResponse
from ..settings_service import build_settings_response, is_off_value, validate_and_coerce

router = APIRouter(prefix="/api/devices", tags=["settings"])


async def _owned(db: AsyncSession, user: User, device_id: str) -> Device:
    device = await db.get(Device, device_id)
    # Settings are live device control, not history — a revoked (unpaired) device reads as not-found
    # so its catalog/values aren't served and can't be changed.
    if (
        not await ownership.owns_device(user, device, db)
        or device.status == DeviceStatusValue.REVOKED
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


async def _onroad(db: AsyncSession, device_id: str) -> bool:
    row = await db.get(DeviceStatus, device_id)
    return bool(row.onroad) if row else False


@router.get("/{device_id}/settings", response_model=SettingsResponse)
async def list_settings(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> SettingsResponse:
    device = await _owned(db, user, device_id)
    return await build_settings_response(db, device, await _onroad(db, device_id))


async def _change(
    request: Request, db: AsyncSession, redis: Redis, user: User, device: Device,
    key: str, value, confirm: bool,
) -> SettingChange:
    defn = await db.get(SettingDefinition, key)
    if defn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown setting")
    if not defn.remote_configurable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This setting is view-only"
        )
    try:
        value = validate_and_coerce(defn, value)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if defn.capability and not (device.capabilities or {}).get(defn.capability):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This setting is not available on this device",
        )
    if defn.danger_level == DangerLevel.DANGEROUS and not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This change is dangerous and requires confirmation",
        )
    if defn.requires_offroad and await _onroad(db, device.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is onroad; this setting can only change while offroad",
        )

    existing = await db.get(DeviceSetting, (device.id, key))
    old_value = existing.value if existing else defn.default_value

    # Physical-consent gate (defense-in-depth; the device re-checks live state authoritatively): a
    # remote write may turn an arm-on-device-only setting OFF or move it between non-off values, but
    # may not move it from off -> non-off. Evaluated against the device's last-reported value.
    if defn.arm_on_device_only and is_off_value(old_value) and not is_off_value(value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This setting must be enabled on the device first",
        )

    change = SettingChange(
        device_id=device.id, key=key, old_value=old_value, new_value=value,
        status=SettingChangeStatus.PENDING, requires_offroad=defn.requires_offroad,
        requested_by=user.id,
    )
    db.add(change)
    await db.flush()
    await record_audit(
        db, action="device.setting.change", actor_type="user", actor_id=str(user.id),
        device_id=device.id, metadata={"key": key, "from": old_value, "to": value,
                                       "change_id": change.id}, ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(change)

    manager = request.app.state.manager
    await manager.send_to_device(
        device.id,
        {"type": FrameType.SET_SETTING.value, "change_id": change.id, "key": key, "value": value},
    )
    return change


@router.post(
    "/{device_id}/settings/{key}/change", response_model=SettingChangeOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def change_setting(
    device_id: str,
    key: str,
    payload: SettingChangeRequest,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> SettingChangeOut:
    # Queues an async SettingChange + dispatches a SET_SETTING command (202), the same shape as the
    # reset sibling — hence POST-to-verb with the key in the path, not PATCH with the key in the body.
    device = await _owned(db, auth.user, device_id)
    if device.status != DeviceStatusValue.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device is not active")
    change = await _change(
        request, db, redis, auth.user, device, key, payload.value, payload.confirm
    )
    return SettingChangeOut.model_validate(change)


@router.post(
    "/{device_id}/settings/{key}/reset", response_model=SettingChangeOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reset_setting(
    device_id: str,
    key: str,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> SettingChangeOut:
    device = await _owned(db, auth.user, device_id)
    defn = await db.get(SettingDefinition, key)
    if defn is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown setting")
    # Reset = change to the default value; confirm implied (returning to a safe baseline).
    change = await _change(
        request, db, redis, auth.user, device, key, defn.default_value, confirm=True
    )
    return SettingChangeOut.model_validate(change)
