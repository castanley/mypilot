"""Web-facing device management (authenticated): claim, list, detail, alias, revoke, status,
audit, and the offroad-only reboot command."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from mypilot_protocol.messages import CommandName, FrameType
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import device_service, ownership
from ..audit import record_audit
from ..config import get_settings
from ..db import get_session
from ..deps import CurrentAuth, client_ip, get_current_user, require_csrf
from ..models import (
    AuditEvent,
    CommandStatus,
    Device,
    DeviceCommand,
    DeviceKey,
    DevicePairing,
    DeviceStatus,
    DeviceStatusValue,
    KeyStatus,
    PairingStatus,
    User,
)
from ..redis_client import (
    consume_pairing_code,
    get_redis,
    mark_offline,
    online_among,
    publish_event,
    rate_limit_ok,
)
from ..schemas import (
    AuditEventOut,
    ClaimRequest,
    ClaimResponse,
    CommandOut,
    DeviceDetail,
    DeviceStatusOut,
    DeviceSummary,
    DeviceUpdate,
    Message,
)

router = APIRouter(prefix="/api/devices", tags=["devices"])
settings = get_settings()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_summary(device: Device, status_row: DeviceStatus | None, online: bool) -> DeviceSummary:
    return DeviceSummary(
        id=device.id,
        alias=device.alias,
        status=device.status,
        platform=device.platform,
        software_version=device.software_version,
        branch=device.branch,
        created_at=device.created_at,
        is_simulated=bool(device.is_simulated),
        online=online,
        # An offline device is never onroad. The stored onroad flag is from the last heartbeat and isn't
        # cleared when a presence key merely EXPIRES (no clean disconnect to run set_offline), so derive
        # it here: onroad only if the device is currently online. Prevents "offline but on the road".
        onroad=bool(online and status_row and status_row.onroad),
        last_heartbeat_at=status_row.last_heartbeat_at if status_row else None,
    )


async def _owned_device(
    db: AsyncSession, user: User, device_id: str, *, allow_revoked: bool = False
) -> Device:
    device = await db.get(Device, device_id)
    # A revoked (unpaired) device is soft-deleted: the row stays for history, but it must read as
    # "not found" to the web (no detail/status/audit/settings, no alias mutation, no telemetry leak).
    # delete_device opts in with allow_revoked=True so re-revoking is idempotent rather than a 404.
    if (
        not await ownership.owns_device(user, device, db)
        or (not allow_revoked and device.status == DeviceStatusValue.REVOKED)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


@router.post("/claim", response_model=ClaimResponse, status_code=status.HTTP_201_CREATED)
async def claim_device(
    payload: ClaimRequest,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> ClaimResponse:
    user = auth.user
    # Throttle claim attempts: the pairing code is short, so an authenticated user could otherwise
    # brute-force codes. Mirror the register start/complete limits, keyed per user + IP.
    rl_key = f"device-claim:{user.id}:{client_ip(request)}"
    if not await rate_limit_ok(
        redis, rl_key, settings.pairing_rate_limit, settings.pairing_rate_window
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts"
        )
    pairing_id = await consume_pairing_code(redis, payload.code)
    if pairing_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired pairing code"
        )

    pairing = await db.get(DevicePairing, pairing_id)
    if pairing is None or pairing.status != PairingStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired pairing code"
        )
    if _aware(pairing.expires_at) < datetime.now(timezone.utc):
        pairing.status = PairingStatus.EXPIRED
        await db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Pairing code expired")

    alias = payload.alias or pairing.hostname or "New device"

    # Re-pairing the same hardware reactivates the existing record (keeping its history/trips) rather
    # than creating a duplicate/zombie row. Match on this owner's device for this hardware_id.
    device = (
        await db.execute(
            select(Device).where(
                ownership.device_owner_filter(user),
                Device.hardware_id == pairing.hardware_id,
            )
        )
    ).scalars().first()

    if device is not None:
        device.alias = alias
        device.status = DeviceStatusValue.PENDING
        device.revoked_at = None
        # Revoke any prior keys before issuing the new one, so re-pairing leaves exactly ONE active
        # key. Otherwise a leaked old key stays usable, and the single-key lookup in deps.py could
        # non-deterministically verify against the wrong active key.
        now = datetime.now(timezone.utc)
        for key in (
            await db.execute(select(DeviceKey).where(DeviceKey.device_id == device.id))
        ).scalars():
            key.status = KeyStatus.REVOKED
            key.revoked_at = now
        # Fresh key for the new pairing; the device may not have a status row if it was pruned.
        db.add(DeviceKey(device_id=device.id, public_key_b64=pairing.public_key_b64))
        if await db.get(DeviceStatus, device.id) is None:
            db.add(DeviceStatus(device_id=device.id, online=False))
    else:
        device = Device(
            owner_id=user.id,
            alias=alias,
            hardware_id=pairing.hardware_id,
            status=DeviceStatusValue.PENDING,
        )
        db.add(device)
        await db.flush()  # assign device.id
        db.add(DeviceKey(device_id=device.id, public_key_b64=pairing.public_key_b64))
        db.add(DeviceStatus(device_id=device.id, online=False))

    pairing.status = PairingStatus.CLAIMED
    pairing.owner_id = user.id
    pairing.alias = alias
    pairing.device_id = device.id
    pairing.claimed_at = datetime.now(timezone.utc)

    await record_audit(
        db,
        action="device.pairing.claimed",
        actor_type="user",
        actor_id=str(user.id),
        device_id=device.id,
        metadata={"pairing_id": pairing.id, "alias": alias},
        ip=client_ip(request),
    )
    await db.commit()
    await db.refresh(device)

    return ClaimResponse(device=_to_summary(device, None, online=False))


@router.get("", response_model=list[DeviceSummary])
async def list_devices(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> list[DeviceSummary]:
    # Exclude revoked (unpaired) devices — they are soft-deleted (row kept for history) but must not
    # appear in the owner's device list.
    devices = (
        (await db.execute(
            select(Device).where(
                ownership.device_owner_filter(user),
                Device.status != DeviceStatusValue.REVOKED,
            )
        )).scalars().all()
    )
    ids = [d.id for d in devices]
    statuses = {
        s.device_id: s
        for s in (
            await db.execute(select(DeviceStatus).where(DeviceStatus.device_id.in_(ids)))
        ).scalars()
    } if ids else {}
    online = await online_among(redis, ids)
    return [_to_summary(d, statuses.get(d.id), d.id in online) for d in devices]


@router.get("/{device_id}", response_model=DeviceDetail)
async def get_device(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> DeviceDetail:
    device = await _owned_device(db, user, device_id)
    status_row = await db.get(DeviceStatus, device.id)
    online = device.id in await online_among(redis, [device.id])
    summary = _to_summary(device, status_row, online)
    status_out = None
    if status_row is not None:
        # status_dict is presence-clamped (online passed in): offline => onroad/driving/track cleared,
        # in ONE shared place. No local clamp needed — that duplication is exactly what let the
        # phantom recur.
        status_out = DeviceStatusOut.model_validate(device_service.status_dict(status_row, online))
    return DeviceDetail(
        **summary.model_dump(),
        hardware_id=device.hardware_id,
        activated_at=device.activated_at,
        status_detail=status_out,
    )


@router.patch("/{device_id}", response_model=DeviceSummary)
async def update_device(
    device_id: str,
    payload: DeviceUpdate,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> DeviceSummary:
    device = await _owned_device(db, auth.user, device_id)
    old_alias = device.alias
    device.alias = payload.alias
    await record_audit(
        db,
        action="device.update",
        actor_type="user",
        actor_id=str(auth.user.id),
        device_id=device.id,
        metadata={"field": "alias", "from": old_alias, "to": payload.alias},
        ip=client_ip(request),
    )
    await db.commit()
    status_row = await db.get(DeviceStatus, device.id)
    online = device.id in await online_among(redis, [device.id])
    await publish_event(
        redis, {"type": "device_event", "device_id": device.id, "event": "updated"}
    )
    return _to_summary(device, status_row, online)


@router.delete("/{device_id}", response_model=Message)
async def delete_device(
    device_id: str,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> Message:
    device = await _owned_device(db, auth.user, device_id, allow_revoked=True)
    now = datetime.now(timezone.utc)
    device.status = DeviceStatusValue.REVOKED
    device.revoked_at = now
    for key in (
        await db.execute(select(DeviceKey).where(DeviceKey.device_id == device.id))
    ).scalars():
        key.status = KeyStatus.REVOKED
        key.revoked_at = now
    await mark_offline(redis, device.id)
    await record_audit(
        db,
        action="device.revoke",
        actor_type="user",
        actor_id=str(auth.user.id),
        device_id=device.id,
        ip=client_ip(request),
    )
    await db.commit()
    await publish_event(redis, {"type": "presence", "device_id": device.id, "online": False})
    return Message(detail="Device revoked")


@router.get("/{device_id}/status", response_model=DeviceStatusOut)
async def device_status(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> DeviceStatusOut:
    device = await _owned_device(db, user, device_id)
    status_row = await db.get(DeviceStatus, device.id)
    online = device.id in await online_among(redis, [device.id])
    if status_row is None:
        return DeviceStatusOut(online=online)
    # Presence-clamped serializer (closes the /status stale-onroad leak the audit found).
    return DeviceStatusOut.model_validate(device_service.status_dict(status_row, online))


@router.get("/{device_id}/audit", response_model=list[AuditEventOut])
async def device_audit(
    device_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    limit: int = 100,
) -> list[AuditEventOut]:
    device = await _owned_device(db, user, device_id)
    rows = (
        await db.execute(
            select(AuditEvent)
            .where(AuditEvent.device_id == device.id)
            .order_by(AuditEvent.created_at.desc())
            .limit(min(limit, 500))
        )
    ).scalars().all()
    return [AuditEventOut.model_validate(r) for r in rows]


@router.post(
    "/{device_id}/reboot", response_model=CommandOut, status_code=status.HTTP_202_ACCEPTED
)
async def reboot_device(
    device_id: str,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> CommandOut:
    device = await _owned_device(db, auth.user, device_id)
    if device.status != DeviceStatusValue.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device is not active")

    # Safety: reboot can affect driving — only allowed offroad.
    status_row = await db.get(DeviceStatus, device.id)
    if status_row is not None and status_row.onroad:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is onroad; reboot is only allowed while offroad",
        )

    command = DeviceCommand(
        device_id=device.id,
        name=CommandName.REBOOT.value,
        args={},
        requires_offroad=True,
        created_by=auth.user.id,
        status=CommandStatus.QUEUED,
    )
    db.add(command)
    await db.flush()

    await record_audit(
        db,
        action="device.command.reboot",
        actor_type="user",
        actor_id=str(auth.user.id),
        device_id=device.id,
        metadata={"command_id": command.id},
        ip=client_ip(request),
    )

    manager = request.app.state.manager
    delivered = await manager.send_to_device(
        device.id,
        {"type": FrameType.COMMAND.value, "id": command.id, "name": command.name, "args": {}},
    )
    if delivered:
        command.status = CommandStatus.SENT
        command.sent_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(command)
    return CommandOut.model_validate(command)
