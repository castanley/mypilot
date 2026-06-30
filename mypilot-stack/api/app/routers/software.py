"""Software releases, channel display, and offroad-gated update/rollback (M7).

An update is a device command: the Stack queues ``software_update`` with the target version +
channel + install URL; the device installs it and reports the new version via heartbeat. Nothing
here changes driving behavior.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from mypilot_protocol.messages import CommandName
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import fork_config, ownership
from ..audit import record_audit
from ..db import get_session
from ..deps import CurrentAuth, client_ip, get_current_user, require_csrf
from ..models import (
    CommandStatus,
    Device,
    DeviceCommand,
    DeviceStatus,
    DeviceStatusValue,
    SoftwareRelease,
    User,
)
from ..redis_client import get_redis, online_among
from ..schemas import (
    CommandOut,
    DeviceSoftwareState,
    SoftwareReleaseOut,
    SoftwareUpdateRequest,
)

router = APIRouter(prefix="/api", tags=["software"])


async def _owned(db: AsyncSession, user: User, device_id: str) -> Device:
    device = await db.get(Device, device_id)
    if not await ownership.owns_device(user, device, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


def _release_out(row: SoftwareRelease, cfg: dict) -> SoftwareReleaseOut:
    out = SoftwareReleaseOut.model_validate(row)
    out.install_url = fork_config.install_url_for(row.channel, cfg)  # derived from fork config
    return out


@router.get("/software/releases", response_model=list[SoftwareReleaseOut])
async def list_releases(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    channel: str | None = None,
) -> list[SoftwareReleaseOut]:
    stmt = select(SoftwareRelease)
    if channel:
        stmt = stmt.where(SoftwareRelease.channel == channel)
    stmt = stmt.order_by(SoftwareRelease.is_current.desc(), SoftwareRelease.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    cfg = await fork_config.get_fork_config(db)
    return [_release_out(r, cfg) for r in rows]


@router.get("/devices/{device_id}/software", response_model=DeviceSoftwareState)
async def device_software(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> DeviceSoftwareState:
    device = await _owned(db, user, device_id)
    status_row = await db.get(DeviceStatus, device.id)
    online = device.id in await online_among(redis, [device.id])
    releases = (
        await db.execute(
            select(SoftwareRelease).order_by(
                SoftwareRelease.is_current.desc(), SoftwareRelease.created_at.desc()
            )
        )
    ).scalars().all()
    cfg = await fork_config.get_fork_config(db)
    # update_state/target_version come from the telemetry envelope: subsystems.software.
    sw_t = (((status_row.telemetry or {}).get("subsystems") or {}).get("software") or {}) if status_row else {}
    return DeviceSoftwareState(
        current_version=device.software_version,
        current_branch=device.branch,
        update_channel=device.update_channel,
        update_state=sw_t.get("update_state"),
        target_version=sw_t.get("target_version"),
        previous_version=device.previous_software_version,
        # Presence-clamped: an offline device is never onroad (don't show a stale "onroad, can't
        # update" hint for a powered-off device whose last heartbeat happened to be mid-drive).
        onroad=bool(online and status_row and status_row.onroad),
        releases=[_release_out(r, cfg) for r in releases],
    )


async def _queue_update(
    db: AsyncSession, manager, user_id: int, device: Device, version: str,
    channel: str | None, install_url: str | None, branch: str | None, ip: str | None,
    *, is_rollback: bool
) -> DeviceCommand:
    status_row = await db.get(DeviceStatus, device.id)
    if status_row is not None and status_row.onroad:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is onroad; software updates are only allowed while offroad",
        )
    if device.software_version == version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Device is already on this version"
        )
    device.previous_software_version = device.software_version
    command = DeviceCommand(
        device_id=device.id,
        name=CommandName.SOFTWARE_UPDATE.value,
        # `branch` is what the on-device updater switches to (derived from the fork config).
        args={"version": version, "channel": channel, "install_url": install_url, "branch": branch},
        requires_offroad=True,
        created_by=user_id,
        status=CommandStatus.QUEUED,
    )
    db.add(command)
    await db.flush()
    await record_audit(
        db,
        action="device.software.rollback" if is_rollback else "device.software.update",
        actor_type="user",
        actor_id=str(user_id),
        device_id=device.id,
        metadata={"version": version, "from": device.previous_software_version,
                  "command_id": command.id},
        ip=ip,
    )
    await db.commit()
    await db.refresh(command)
    delivered = await manager.send_to_device(
        device.id,
        {"type": "command", "id": command.id, "name": command.name, "args": command.args},
    )
    if delivered:
        command.status = CommandStatus.SENT
        command.sent_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(command)
    return command


@router.post(
    "/devices/{device_id}/software/update",
    response_model=CommandOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def update_software(
    device_id: str,
    payload: SoftwareUpdateRequest,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> CommandOut:
    device = await _owned(db, auth.user, device_id)
    if device.status != DeviceStatusValue.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device is not active")
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Software update requires confirmation"
        )
    release = (
        await db.execute(select(SoftwareRelease).where(SoftwareRelease.version == payload.version))
    ).scalar_one_or_none()
    if release is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown release")
    cfg = await fork_config.get_fork_config(db)
    command = await _queue_update(
        db, request.app.state.manager, auth.user.id, device, release.version,
        release.channel, fork_config.install_url_for(release.channel, cfg),
        fork_config.branch_for(release.channel, cfg), client_ip(request), is_rollback=False,
    )
    return CommandOut.model_validate(command)


@router.post(
    "/devices/{device_id}/software/rollback",
    response_model=CommandOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rollback_software(
    device_id: str,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> CommandOut:
    device = await _owned(db, auth.user, device_id)
    target = device.previous_software_version
    if not target:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No previous version to roll back to"
        )
    release = (
        await db.execute(select(SoftwareRelease).where(SoftwareRelease.version == target))
    ).scalar_one_or_none()
    cfg = await fork_config.get_fork_config(db)
    channel = release.channel if release else (device.update_channel or "release")
    install_url = fork_config.install_url_for(channel, cfg) if channel in ("release", "staging") else None
    branch = fork_config.branch_for(channel, cfg) if channel in ("release", "staging") else None
    command = await _queue_update(
        db, request.app.state.manager, auth.user.id, device, target, channel, install_url,
        branch, client_ip(request), is_rollback=True,
    )
    return CommandOut.model_validate(command)
