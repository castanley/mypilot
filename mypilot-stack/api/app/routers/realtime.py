"""WebSocket endpoints: device telemetry/commands and browser live updates."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from mypilot_protocol.crypto import verify
from mypilot_protocol.messages import FrameType, ws_auth_message
from pydantic import ValidationError
from sqlalchemy import select

from ..config import get_settings
from ..db import SessionLocal
from ..device_service import apply_heartbeat, record_command_result, set_offline
from ..models import (
    CommandStatus,
    Device,
    DeviceCommand,
    DeviceKey,
    DeviceStatusValue,
    KeyStatus,
    Session,
    SettingChange,
    SettingChangeStatus,
    User,
)
from ..redis_client import mark_online, publish_event
from ..schemas import HeartbeatRequest
from ..security import generate_token, hash_token
from ..settings_service import apply_settings_sync, record_setting_result

router = APIRouter(tags=["realtime"])
log = logging.getLogger("mypilot.realtime")
settings = get_settings()


async def _user_from_ws(websocket: WebSocket) -> User | None:
    raw = websocket.cookies.get(settings.session_cookie_name)
    if not raw:
        return None
    token_hash = hash_token(raw)
    async with SessionLocal() as db:
        session = (
            await db.execute(select(Session).where(Session.token_hash == token_hash))
        ).scalar_one_or_none()
        if session is None or session.revoked_at is not None:
            return None
        expires = session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            return None
        return await db.get(User, session.user_id)


@router.websocket("/api/realtime/web")
async def realtime_web(websocket: WebSocket) -> None:
    user = await _user_from_ws(websocket)
    if user is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    manager = websocket.app.state.manager
    # Tag the socket with its authenticated user so device events fan out only to that device's owner.
    await manager.add_web(websocket, user.id)
    try:
        # The browser is a passive subscriber; we just keep the socket open.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.remove_web(websocket)


async def _authenticate_device(websocket: WebSocket, nonce: str) -> Device | None:
    try:
        frame = await websocket.receive_json()
    except (WebSocketDisconnect, ValueError):
        return None
    if frame.get("type") != FrameType.AUTH.value:
        return None
    device_id = frame.get("device_id")
    signature = frame.get("signature")
    if not device_id or not signature:
        return None

    async with SessionLocal() as db:
        device = await db.get(Device, device_id)
        if device is None or device.status != DeviceStatusValue.ACTIVE:
            return None
        key = (
            await db.execute(
                select(DeviceKey).where(
                    DeviceKey.device_id == device_id, DeviceKey.status == KeyStatus.ACTIVE
                )
            )
        ).scalars().first()
        if key is None:
            return None
        if not verify(key.public_key_b64, signature, ws_auth_message(nonce)):
            return None
        return device


async def _deliver_queued_commands(websocket: WebSocket, device_id: str) -> None:
    async with SessionLocal() as db:
        commands = (
            await db.execute(
                select(DeviceCommand).where(
                    DeviceCommand.device_id == device_id,
                    DeviceCommand.status == CommandStatus.QUEUED,
                )
            )
        ).scalars().all()
        for cmd in commands:
            await websocket.send_json(
                {"type": FrameType.COMMAND.value, "id": cmd.id, "name": cmd.name, "args": cmd.args}
            )
            cmd.status = CommandStatus.SENT
            cmd.sent_at = datetime.now(timezone.utc)
        if commands:
            await db.commit()

        # Deliver any pending setting changes (awaiting a result).
        changes = (
            await db.execute(
                select(SettingChange).where(
                    SettingChange.device_id == device_id,
                    SettingChange.status == SettingChangeStatus.PENDING,
                )
            )
        ).scalars().all()
        for ch in changes:
            await websocket.send_json(
                {"type": FrameType.SET_SETTING.value, "change_id": ch.id, "key": ch.key,
                 "value": ch.new_value}
            )


@router.websocket("/api/realtime/device")
async def realtime_device(websocket: WebSocket) -> None:
    await websocket.accept()
    redis = websocket.app.state.redis
    manager = websocket.app.state.manager

    # 1. Challenge/response handshake proving possession of the device private key.
    nonce = generate_token(16)
    await websocket.send_json({"type": FrameType.AUTH_CHALLENGE.value, "nonce": nonce})
    device = await _authenticate_device(websocket, nonce)
    if device is None:
        await websocket.send_json({"type": FrameType.AUTH_FAIL.value, "reason": "unauthorized"})
        await websocket.close(code=1008)
        return

    device_id = device.id
    await websocket.send_json({"type": FrameType.AUTH_OK.value, "device_id": device_id})

    # Register + mark online + flush queued commands, then stream — all inside the try so the
    # `finally` (remove_device + set_offline) runs if any of these fail. Done outside the try, a
    # send failure during queued-command delivery would leave a stale presence key + a dead socket
    # registered in the manager.
    try:
        await manager.add_device(device_id, websocket)
        await mark_online(redis, device_id, settings.presence_ttl_seconds)
        await publish_event(redis, {"type": "presence", "device_id": device_id, "online": True})
        await _deliver_queued_commands(websocket, device_id)

        # Stream loop.
        while True:
            frame = await websocket.receive_json()
            ftype = frame.get("type")

            if ftype == FrameType.HEARTBEAT.value:
                await mark_online(redis, device_id, settings.presence_ttl_seconds)

            elif ftype == FrameType.STATUS.value:
                # Validate the frame in isolation: a single malformed STATUS frame (e.g. a buggy device
                # emitting a NaN/out-of-range coordinate the schema now rejects) must NOT escape to the
                # connection-level handler, whose finally clause runs set_offline — that would flap the
                # device's socket/presence/trail on every bad frame. Skip just this frame, mirroring the
                # REST path's per-request 422 rejection; a healthy device stays connected and online.
                try:
                    payload = HeartbeatRequest(**(frame.get("payload") or {}))
                except ValidationError:
                    log.warning("device %s sent an invalid STATUS frame; skipping it", device_id)
                    continue
                async with SessionLocal() as db:
                    fresh = await db.get(Device, device_id)
                    if fresh is not None:
                        await apply_heartbeat(db, redis, fresh, payload)

            elif ftype == FrameType.COMMAND_RESULT.value:
                async with SessionLocal() as db:
                    fresh = await db.get(Device, device_id)
                    if fresh is not None:
                        await record_command_result(
                            db,
                            redis,
                            fresh,
                            frame.get("id"),
                            bool(frame.get("ok")),
                            frame.get("detail"),
                        )

            elif ftype == FrameType.SETTINGS_SYNC.value:
                async with SessionLocal() as db:
                    fresh = await db.get(Device, device_id)
                    if fresh is not None:
                        await apply_settings_sync(
                            db, fresh, frame.get("capabilities"), frame.get("values")
                        )

            elif ftype == FrameType.SETTING_RESULT.value:
                async with SessionLocal() as db:
                    fresh = await db.get(Device, device_id)
                    if fresh is not None:
                        await record_setting_result(
                            db, redis, fresh, frame.get("change_id"), bool(frame.get("ok")),
                            frame.get("value"), frame.get("detail"),
                        )
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("device websocket error for %s", device_id)
    finally:
        await manager.remove_device(device_id, websocket)
        async with SessionLocal() as db:
            await set_offline(db, redis, device_id)
