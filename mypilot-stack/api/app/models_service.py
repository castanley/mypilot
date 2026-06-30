"""Model catalog views and the offroad-gated switch/rollback flow (M5).

A switch is a device command: the Stack queues ``switch_model`` (with the artifact's sha256); the
device downloads the artifact, verifies the checksum, activates it, and reports the new active
model back via heartbeat + command result. Nothing here changes driving behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from mypilot_protocol.messages import CommandName
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import record_audit
from .models import (
    CommandStatus,
    Device,
    DeviceCommand,
    DeviceStatus,
    Model,
)
from .schemas import DeviceModelsResponse, DeviceModelView, ModelOut


def _device_type(device: Device) -> str | None:
    return (device.capabilities or {}).get("device_type")


async def build_device_models(
    db: AsyncSession, device: Device, onroad: bool
) -> DeviceModelsResponse:
    models = (await db.execute(select(Model).order_by(Model.is_default.desc(), Model.name))).scalars().all()
    status_row = await db.get(DeviceStatus, device.id)
    # Device-reported models now live in the telemetry envelope: subsystems.models.{installed_refs,available}.
    models_t = (((status_row.telemetry or {}).get("subsystems") or {}).get("models") or {}) if status_row else {}
    installed = set(models_t.get("installed_refs") or [])
    available = models_t.get("available") or []  # RealDevice: Model Manager catalog
    active = device.active_model_key
    dtype = _device_type(device)

    views: list[DeviceModelView] = []
    catalog_keys: set[str] = set()

    def _reported_view(key: str, name: str, generation=None, runner=None) -> DeviceModelView:
        gen = f"generation {generation}" if generation else "an on-device model"
        return DeviceModelView(
            id=key, key=key, name=name or key,
            description=f"SunnyPilot driving model ({gen}). Downloaded + verified on the device when selected.",
            version="", generation=generation, runner=runner, build_time=None, checksum="",
            size_bytes=0, compatible_device_types=[], compatible_versions=[], is_default=False,
            created_at=datetime.now(timezone.utc),
            active=(key == active), installed=(key in installed) or (key == active), compatible=True,
        )

    for m in models:
        catalog_keys.add(m.key)
        base = ModelOut.model_validate(m).model_dump()
        compatible = (not m.compatible_device_types) or (dtype in m.compatible_device_types)
        views.append(
            DeviceModelView(
                **base,
                active=(m.key == active),
                installed=(m.key in installed) or (m.key == active),
                compatible=compatible,
            )
        )

    # Device-reported available models (real device: the on-device Model Manager catalog).
    for am in available:
        key = am.get("key") if isinstance(am, dict) else None
        if not key or key in catalog_keys:
            continue
        catalog_keys.add(key)
        views.append(_reported_view(key, am.get("name"), am.get("generation"), am.get("runner")))

    # Fallback: surface the active/installed model strings if nothing else covered them.
    reported = set(installed)
    if active:
        reported.add(active)
    for key in sorted(reported):
        if key not in catalog_keys:
            catalog_keys.add(key)
            views.append(_reported_view(key, key))

    return DeviceModelsResponse(active_model_key=active, onroad=onroad, models=views)


async def issue_model_switch(
    db: AsyncSession,
    manager,
    user_id: int,
    device: Device,
    model_key: str,
    confirm: bool,
    ip: str | None,
    *,
    is_rollback: bool = False,
) -> DeviceCommand:
    model = (
        await db.execute(select(Model).where(Model.key == model_key))
    ).scalar_one_or_none()
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown model")

    dtype = _device_type(device)
    if model.compatible_device_types and dtype and dtype not in model.compatible_device_types:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This model is not compatible with this device",
        )
    # Switching to a non-default model is a meaningful change -> require confirmation.
    if not is_rollback and not model.is_default and not confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Switching models requires confirmation",
        )
    # Safety: model switching can affect driving -> offroad only.
    status_row = await db.get(DeviceStatus, device.id)
    if status_row is not None and status_row.onroad:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is onroad; model switching is only allowed while offroad",
        )
    if model.key == device.active_model_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This model is already active"
        )

    # Capture the rollback target (the model active right now) before switching.
    device.previous_model_key = device.active_model_key

    command = DeviceCommand(
        device_id=device.id,
        name=CommandName.SWITCH_MODEL.value,
        args={"model_key": model.key, "checksum": model.checksum, "version": model.version},
        requires_offroad=True,
        created_by=user_id,
        status=CommandStatus.QUEUED,
    )
    db.add(command)
    await db.flush()
    await record_audit(
        db,
        action="device.model.rollback" if is_rollback else "device.model.switch",
        actor_type="user",
        actor_id=str(user_id),
        device_id=device.id,
        metadata={
            "model_key": model.key,
            "from": device.previous_model_key,
            "command_id": command.id,
        },
        ip=ip,
    )
    await db.commit()
    await db.refresh(command)

    delivered = await manager.send_to_device(
        device.id,
        {
            "type": "command",
            "id": command.id,
            "name": command.name,
            "args": command.args,
        },
    )
    if delivered:
        command.status = CommandStatus.SENT
        command.sent_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(command)
    return command
