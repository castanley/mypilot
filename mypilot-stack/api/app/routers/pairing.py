"""Device-facing pairing endpoints (unauthenticated, rate-limited).

The web-facing claim endpoint lives in ``devices.py`` (it requires a logged-in user).
See ``docs/device-registration.md`` for the full handshake.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from mypilot_protocol.crypto import public_key_from_b64, verify
from mypilot_protocol.messages import pairing_challenge
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_audit
from ..config import get_settings
from ..db import get_session
from ..deps import client_ip
from ..models import Device, DevicePairing, DeviceStatusValue, PairingStatus
from ..redis_client import get_redis, rate_limit_ok, store_pairing_code
from ..schemas import (
    DeviceConfig,
    RegisterCompleteRequest,
    RegisterCompleteResponse,
    RegisterStartRequest,
    RegisterStartResponse,
)
from ..security import generate_pairing_code

router = APIRouter(prefix="/api/devices/register", tags=["pairing"])
settings = get_settings()

POLL_INTERVAL_SECONDS = 3


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@router.post("/start", response_model=RegisterStartResponse)
async def register_start(
    payload: RegisterStartRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> RegisterStartResponse:
    rl_key = f"pair-start:{client_ip(request)}"
    if not await rate_limit_ok(
        redis, rl_key, settings.pairing_rate_limit, settings.pairing_rate_window
    ):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")

    # Reject a malformed Ed25519 public key before persisting anything.
    try:
        public_key_from_b64(payload.public_key)
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid public key")

    now = datetime.now(timezone.utc)
    code = generate_pairing_code(settings.pairing_code_length)
    pairing = DevicePairing(
        code=code,
        hardware_id=payload.hardware_id,
        public_key_b64=payload.public_key,
        hostname=payload.hostname,
        status=PairingStatus.PENDING,
        expires_at=now + timedelta(seconds=settings.pairing_code_ttl_seconds),
    )
    db.add(pairing)
    await db.commit()
    await db.refresh(pairing)

    await store_pairing_code(redis, code, pairing.id, settings.pairing_code_ttl_seconds)

    return RegisterStartResponse(
        pairing_id=pairing.id,
        code=code,
        expires_at=pairing.expires_at,
        poll_interval=POLL_INTERVAL_SECONDS,
    )


@router.post("/complete", response_model=RegisterCompleteResponse)
async def register_complete(
    payload: RegisterCompleteRequest,
    request: Request,
    db: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> RegisterCompleteResponse:
    rl_key = f"pair-complete:{client_ip(request)}"
    if not await rate_limit_ok(
        redis, rl_key, settings.pairing_rate_limit, settings.pairing_rate_window
    ):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many attempts")

    pairing = await db.get(DevicePairing, payload.pairing_id)
    if pairing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown pairing")

    config = DeviceConfig(
        heartbeat_interval=settings.heartbeat_interval_seconds,
        presence_ttl=settings.presence_ttl_seconds,
    )

    # Idempotent: already completed.
    if pairing.status == PairingStatus.COMPLETED and pairing.device_id:
        return RegisterCompleteResponse(status="active", device_id=pairing.device_id, config=config)

    # Expired before being claimed.
    if pairing.status != PairingStatus.COMPLETED and _aware(pairing.expires_at) < datetime.now(
        timezone.utc
    ):
        pairing.status = PairingStatus.EXPIRED
        await db.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Pairing expired")

    # Not yet claimed by a user in the web UI.
    if pairing.status == PairingStatus.PENDING:
        return RegisterCompleteResponse(status="pending")

    # Claimed: the device must prove possession of its private key.
    challenge = pairing_challenge(pairing.id)
    if not verify(pairing.public_key_b64, payload.signature, challenge):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid device signature"
        )

    device = await db.get(Device, pairing.device_id) if pairing.device_id else None
    if device is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device record missing")

    now = datetime.now(timezone.utc)
    device.status = DeviceStatusValue.ACTIVE
    device.activated_at = now
    pairing.status = PairingStatus.COMPLETED
    pairing.completed_at = now
    await record_audit(
        db,
        action="device.pairing.completed",
        actor_type="device",
        actor_id=device.id,
        device_id=device.id,
        metadata={"pairing_id": pairing.id},
    )
    await db.commit()

    return RegisterCompleteResponse(status="active", device_id=device.id, config=config)
