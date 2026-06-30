"""Heartbeat write-behind coalescing (scale Stage B1).

With heartbeat_persist_interval_seconds > 0 the DeviceStatus row is committed only on a coalesced
cadence (every N seconds + forced on a new row / onroad transition), instead of every beat — cutting
Postgres write volume at fleet scale. The live map is unaffected: the realtime device_status event is
published EVERY beat from the in-hand data, and the working trail lives in Redis between skipped
commits. These tests pin that contract. (interval==0, the default, is covered by the other heartbeat
tests as today's every-beat behavior.)
"""

from __future__ import annotations

import json

import fakeredis.aioredis
import pytest
from app import device_service
from app.db import SessionLocal
from app.models import Device, DeviceStatus, DeviceStatusValue, User
from app.redis_client import get_live_track
from app.schemas import HeartbeatRequest
from app.security import hash_password


class RecordingRedis(fakeredis.aioredis.FakeRedis):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.published: list[dict] = []

    async def publish(self, channel, message):
        self.published.append(json.loads(message))
        return await super().publish(channel, message)


def _hb(onroad=True, lat=None, lon=None) -> HeartbeatRequest:
    sub = {}
    if lat is not None:
        sub = {"driving": {"latitude": lat, "longitude": lon, "speed_ms": 10.0}}
    return HeartbeatRequest.model_validate({"onroad": onroad, "subsystems": sub})


async def _seed_device(did="wb-dev") -> Device:
    async with SessionLocal() as db:
        user = User(username=f"u-{did}", password_hash=hash_password("x" * 10), is_admin=True)
        db.add(user)
        await db.flush()
        db.add(Device(id=did, owner_id=user.id, alias="WB", status=DeviceStatusValue.ACTIVE))
        await db.commit()
        return await db.get(Device, did)


async def _persisted_heartbeat_at(did="wb-dev"):
    """Read the COMMITTED row's last_heartbeat_at (changes only when a beat actually persisted)."""
    async with SessionLocal() as db:
        row = await db.get(DeviceStatus, did)
        return row.last_heartbeat_at if row else None


@pytest.mark.asyncio
async def test_coalesced_beats_skip_db_writes_but_always_emit_event(app, monkeypatch):
    monkeypatch.setattr(device_service.settings, "heartbeat_persist_interval_seconds", 3600)
    redis = RecordingRedis(decode_responses=True)
    device = await _seed_device()

    # Beat 1: new row -> forced persist.
    async with SessionLocal() as db:
        dev = await db.get(Device, device.id)
        await device_service.apply_heartbeat(db, redis, dev, _hb(onroad=True))
    first_persisted = await _persisted_heartbeat_at()
    assert first_persisted is not None
    assert len(redis.published) == 1  # event fired

    # Beats 2 & 3: within the interval, same onroad -> NO new commit, but events STILL fire.
    for _ in range(2):
        async with SessionLocal() as db:
            dev = await db.get(Device, device.id)
            await device_service.apply_heartbeat(db, redis, dev, _hb(onroad=True))
    assert await _persisted_heartbeat_at() == first_persisted  # row NOT re-committed
    assert len(redis.published) == 3  # but every beat emitted a device_status event
    assert all(e["type"] == "device_status" and e["status"]["online"] for e in redis.published)


@pytest.mark.asyncio
async def test_onroad_transition_forces_immediate_persist(app, monkeypatch):
    monkeypatch.setattr(device_service.settings, "heartbeat_persist_interval_seconds", 3600)
    redis = RecordingRedis(decode_responses=True)
    device = await _seed_device("wb-trans")

    async with SessionLocal() as db:
        dev = await db.get(Device, device.id)
        await device_service.apply_heartbeat(db, redis, dev, _hb(onroad=False))  # beat 1: new row persists
    t1 = await _persisted_heartbeat_at("wb-trans")

    # offroad -> onroad transition must persist immediately even though we're inside the interval.
    async with SessionLocal() as db:
        dev = await db.get(Device, device.id)
        await device_service.apply_heartbeat(db, redis, dev, _hb(onroad=True))
    t2 = await _persisted_heartbeat_at("wb-trans")
    assert t2 is not None and t2 != t1  # row was re-committed on the transition

    async with SessionLocal() as db:
        row = await db.get(DeviceStatus, "wb-trans")
        assert row.onroad is True  # the durable row reflects the transition, not a stale flag


@pytest.mark.asyncio
async def test_live_track_accumulates_across_skipped_commits(app, monkeypatch):
    monkeypatch.setattr(device_service.settings, "heartbeat_persist_interval_seconds", 3600)
    redis = RecordingRedis(decode_responses=True)
    device = await _seed_device("wb-track")

    # Three onroad beats at distinct positions (far enough apart to each append a point). Only the
    # first commits (new row); the trail must still grow in Redis across the skipped commits.
    pts = [(37.4419, -122.1430), (37.4500, -122.1500), (37.4580, -122.1570)]
    for lat, lon in pts:
        async with SessionLocal() as db:
            dev = await db.get(Device, device.id)
            await device_service.apply_heartbeat(db, redis, dev, _hb(onroad=True, lat=lat, lon=lon))

    track = await get_live_track(redis, "wb-track")
    assert track is not None and len(track) == 3, track  # all three points accumulated in Redis
    # The latest event carries the full accumulated trail (the live map stays correct).
    assert redis.published[-1]["status"]["live_track"] == track
