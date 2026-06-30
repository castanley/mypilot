"""Heartbeat hot-path event contract (scale-tuning guard).

apply_heartbeat must publish EXACTLY ONE event per beat — a device_status carrying online=True — not a
separate presence:true plus a device_status. The redundant presence publish was removed because it
doubled publish volume + subscriber fan-out on the hottest path in the system for zero client effect
(the web reducer already folds online from the device_status payload). This test pins that contract so
it can't silently regress. set_offline still emits presence:false (no status event fires on disconnect).
"""

from __future__ import annotations

import json

import fakeredis.aioredis
import pytest
from app import device_service
from app.db import SessionLocal
from app.models import Device, DeviceStatusValue, User
from app.schemas import HeartbeatRequest
from app.security import hash_password


class RecordingRedis(fakeredis.aioredis.FakeRedis):
    """A FakeRedis that records every publish() so a test can assert the exact events a hot-path
    function fans out (fakeredis pubsub delivery timing is too flaky to poll reliably)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.published: list[dict] = []

    async def publish(self, channel, message):
        self.published.append(json.loads(message))
        return await super().publish(channel, message)


def _heartbeat(onroad: bool = True) -> HeartbeatRequest:
    return HeartbeatRequest.model_validate({"onroad": onroad, "subsystems": {}})


@pytest.mark.asyncio
async def test_heartbeat_publishes_single_device_status_event(app):
    redis = RecordingRedis(decode_responses=True)
    async with SessionLocal() as db:
        user = User(username="hbowner", password_hash=hash_password("x" * 10), is_admin=True)
        db.add(user)
        await db.flush()
        db.add(Device(id="hb-dev", owner_id=user.id, alias="HB", status=DeviceStatusValue.ACTIVE))
        await db.commit()
        device = await db.get(Device, "hb-dev")

        await device_service.apply_heartbeat(db, redis, device, _heartbeat(onroad=True))

    # Exactly one event, and it's the device_status (NOT a separate presence:true).
    assert len(redis.published) == 1, redis.published
    evt = redis.published[0]
    assert evt["type"] == "device_status"
    assert evt["device_id"] == "hb-dev"
    assert evt["status"]["online"] is True  # online carried on the status payload
    assert evt["status"]["onroad"] is True


@pytest.mark.asyncio
async def test_set_offline_still_emits_presence_false(app):
    redis = RecordingRedis(decode_responses=True)
    async with SessionLocal() as db:
        user = User(username="offowner", password_hash=hash_password("x" * 10), is_admin=True)
        db.add(user)
        await db.flush()
        db.add(Device(id="off-dev", owner_id=user.id, alias="OFF", status=DeviceStatusValue.ACTIVE))
        await db.commit()
        device = await db.get(Device, "off-dev")
        await device_service.apply_heartbeat(db, redis, device, _heartbeat(onroad=True))
        redis.published.clear()  # ignore the heartbeat's event; we want set_offline's

        await device_service.set_offline(db, redis, "off-dev")

    # Disconnect path is the one place presence:false must still fire (no status event there).
    assert redis.published == [{"type": "presence", "device_id": "off-dev", "online": False}]
