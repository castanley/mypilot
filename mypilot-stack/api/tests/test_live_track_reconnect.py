"""The live trail must SURVIVE a transient offline (WS drop / presence-TTL lapse) mid-drive.

Bug seen on a real drive: the blue live-map line kept restarting from wherever the device reconnected,
losing the route driven before each drop. Root cause: on cellular the device WS drops (and its presence
TTL lapses) many times mid-drive; every drop ran set_offline, which wiped status.live_track. "Offline"
is a PRESENCE fact, not "the drive ended" — so the trail must persist across a transient drop and resume
on reconnect, and only reset when a genuinely NEW drive begins (a long heartbeat gap) or the device goes
offroad. These tests pin that: a quick reconnect RESUMES the same trail; a long gap starts FRESH.
"""

from __future__ import annotations

import fakeredis.aioredis
import pytest
from app import device_service
from app.db import SessionLocal
from app.models import Device, DeviceStatus, DeviceStatusValue, User
from app.schemas import HeartbeatRequest
from app.security import hash_password


def _hb(lat, lon, onroad=True) -> HeartbeatRequest:
    return HeartbeatRequest.model_validate(
        {"onroad": onroad, "subsystems": {"driving": {"latitude": lat, "longitude": lon, "speed_ms": 10.0}}}
    )


async def _seed_device(did: str) -> Device:
    async with SessionLocal() as db:
        user = User(username=f"u-{did}", password_hash=hash_password("x" * 10), is_admin=True)
        db.add(user)
        await db.flush()
        db.add(Device(id=did, owner_id=user.id, alias="car", status=DeviceStatusValue.ACTIVE))
        await db.commit()
        return await db.get(Device, did)


async def _drive(device, redis, points):
    async with SessionLocal() as db:
        dev = await db.get(Device, device.id)
        for lat, lon in points:
            await device_service.apply_heartbeat(db, redis, dev, _hb(lat, lon))


async def _trail(did):
    async with SessionLocal() as db:
        s = await db.get(DeviceStatus, did)
        return list(s.live_track or [])


async def db_last_hb(did):
    """The COMMITTED last_heartbeat_at (advances only on a persisted beat)."""
    async with SessionLocal() as db:
        s = await db.get(DeviceStatus, did)
        return s.last_heartbeat_at if s else None


@pytest.mark.asyncio
async def test_transient_offline_preserves_trail_and_resumes(app):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    device = await _seed_device("recon-1")

    await _drive(device, redis, [(37.00, -122.0), (37.01, -122.0), (37.02, -122.0)])
    assert len(await _trail("recon-1")) == 3

    # Transient WS drop mid-drive: the device WS `finally` runs set_offline.
    async with SessionLocal() as db:
        await device_service.set_offline(db, redis, "recon-1")
        s = await db.get(DeviceStatus, "recon-1")
        assert s.online is False
        assert s.onroad is False           # offline can't be onroad (no phantom liveness)
        assert len(s.live_track or []) == 3  # ...but the TRAIL IS PRESERVED (was wiped before the fix)

    # Reconnect a moment later (transient): the trail RESUMES — appends, does not restart.
    await _drive(device, redis, [(37.03, -122.0)])
    resumed = await _trail("recon-1")
    assert len(resumed) == 4, "a transient reconnect must resume the trail, not reset it"
    assert resumed[0] == [37.0, -122.0]     # original start retained
    assert resumed[-1] == [37.03, -122.0]


@pytest.mark.asyncio
async def test_reconnect_past_presence_ttl_but_under_new_drive_gap_resumes(app):
    """The critical real-world window: a cellular drop LONGER than presence_ttl (so the device went
    'offline') but SHORTER than the new-drive gap. The new-drive decision must be made by the GAP, not
    by the last-beat key expiring — so the key's TTL must exceed the gap. If the key TTL'd at
    presence_ttl (30s) this reconnect would wrongly reset the trail (the bug this test guards)."""
    from app.redis_client import _last_beat_key
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    device = await _seed_device("recon-win")

    await _drive(device, redis, [(37.0, -122.0), (37.01, -122.0), (37.02, -122.0)])
    # The last-beat key must outlive the new-drive gap so key-expiry never classifies a reconnect.
    assert await redis.ttl(_last_beat_key("recon-win")) > device_service._LIVE_TRACK_NEW_DRIVE_GAP_S

    # Simulate a ~45s drop (past the 30s presence TTL, well under the 180s gap) by rewinding last-beat.
    cur = float(await redis.get(_last_beat_key("recon-win")))
    await redis.set(_last_beat_key("recon-win"), cur - 45.0)
    async with SessionLocal() as db:
        await device_service.set_offline(db, redis, "recon-win")  # the drop marked it offline

    await _drive(device, redis, [(37.03, -122.0)])
    assert len(await _trail("recon-win")) == 4, "a 45s drop (offline but not a new drive) must resume, not reset"


@pytest.mark.asyncio
async def test_new_drive_after_long_gap_starts_fresh(app):
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    device = await _seed_device("recon-2")

    await _drive(device, redis, [(37.00, -122.0), (37.01, -122.0)])
    assert len(await _trail("recon-2")) == 2

    # Device goes offline (drive ends) and stays gone well past the new-drive gap threshold. The gap is
    # measured from the Redis last-beat key (presence-TTL'd), so a long offline is simulated by aging it
    # past the threshold (a real long offline would let it TTL-expire, handled by the None branch too).
    from app.redis_client import get_last_beat_at, set_last_beat_at
    async with SessionLocal() as db:
        await device_service.set_offline(db, redis, "recon-2")
    old = (await get_last_beat_at(redis, "recon-2")) - (device_service._LIVE_TRACK_NEW_DRIVE_GAP_S + 60)
    await set_last_beat_at(redis, "recon-2", old, 3600)

    # A NEW drive begins far away — must NOT append to the previous drive's stale trail.
    await _drive(device, redis, [(40.0, -120.0)])
    fresh = await _trail("recon-2")
    assert fresh == [[40.0, -120.0]], "a genuinely new drive (long gap) must start a fresh trail"


@pytest.mark.asyncio
async def test_writebehind_continuous_drive_keeps_growing(app, monkeypatch):
    """Regression for the write-behind clock bug: with a large persist interval the DB
    last_heartbeat_at only advances on a COMMITTED beat, so gating new-drive on it would make a healthy
    CONTINUOUS drive look fresh once wall-clock passed the 180s gap and collapse its trail. The gap is
    measured from the per-beat Redis last-beat key (bumped EVERY beat), so consecutive beats are always
    seconds apart and the trail keeps growing however rarely it commits. We assert the invariant the
    committed-clock version would violate: after the first (forced) persist, the DB clock is pinned, yet
    many more beats keep extending the trail."""
    monkeypatch.setattr(device_service.settings, "heartbeat_persist_interval_seconds", 3600)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    device = await _seed_device("recon-wb2")
    from app.redis_client import get_last_beat_at, get_live_track

    # A continuous drive: 6 beats. Only the first commits (new row); the rest are coalesced, so the DB
    # last_heartbeat_at stays pinned at beat 1. Each beat bumps the Redis last-beat to ~now, so the gap
    # never trips new-drive and the Redis trail grows monotonically.
    await _drive(device, redis, [(37.0 + i * 0.01, -122.0) for i in range(6)])
    committed = (await db_last_hb("recon-wb2"))
    assert len(await get_live_track(redis, "recon-wb2") or []) == 6, "continuous write-behind drive must keep ALL points"
    # The Redis last-beat is fresh (drives new-drive detection), independent of the pinned DB clock.
    assert await get_last_beat_at(redis, "recon-wb2") is not None
    assert committed is not None  # sanity: the row did commit once


@pytest.mark.asyncio
async def test_offroad_still_clears_trail(app):
    """A genuine park (device reports onroad=false) still clears the trail — that lifecycle is unchanged;
    only the transient-offline wipe was removed."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    device = await _seed_device("recon-3")
    await _drive(device, redis, [(37.0, -122.0), (37.01, -122.0)])
    assert len(await _trail("recon-3")) == 2
    async with SessionLocal() as db:
        dev = await db.get(Device, device.id)
        await device_service.apply_heartbeat(db, redis, dev, _hb(37.02, -122.0, onroad=False))
    assert await _trail("recon-3") == []  # offroad clears (None -> [] via `or []`)


@pytest.mark.asyncio
async def test_transient_offline_preserves_trail_writebehind(app, monkeypatch):
    """Same guarantee on the write-behind path (interval>0), where the trail lives in Redis: a transient
    offline keeps the Redis trail (presence-TTL'd) so a prompt reconnect resumes it."""
    monkeypatch.setattr(device_service.settings, "heartbeat_persist_interval_seconds", 3600)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    device = await _seed_device("recon-wb")
    from app.redis_client import get_live_track

    await _drive(device, redis, [(37.0, -122.0), (37.01, -122.0), (37.02, -122.0)])
    assert len(await get_live_track(redis, "recon-wb") or []) == 3

    async with SessionLocal() as db:
        await device_service.set_offline(db, redis, "recon-wb")
    # set_offline must NOT delete the Redis trail (only the persisted-clock key).
    assert len(await get_live_track(redis, "recon-wb") or []) == 3

    await _drive(device, redis, [(37.03, -122.0)])
    assert len(await get_live_track(redis, "recon-wb") or []) == 4  # resumed


@pytest.mark.asyncio
async def test_writebehind_reconnect_30_180s_window_resumes(app, monkeypatch):
    """Write-behind (interval>0): the trail lives in the Redis live:track key. That key MUST outlive the
    new-drive gap (like the last-beat key), otherwise a reconnect in the 30-180s window (past presence
    TTL, under the gap) finds no trail and truncates — the same bug the last-beat TTL fix closed, in the
    sibling data key. Assert both keys carry the long TTL and a 45s-window reconnect resumes."""
    monkeypatch.setattr(device_service.settings, "heartbeat_persist_interval_seconds", 3600)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    device = await _seed_device("recon-wbwin")
    from app.redis_client import _last_beat_key, _live_track_key, get_live_track

    await _drive(device, redis, [(37.0, -122.0), (37.01, -122.0), (37.02, -122.0)])
    # BOTH keys must outlive the new-drive gap — the trail data key, not just the last-beat marker.
    gap = device_service._LIVE_TRACK_NEW_DRIVE_GAP_S
    assert await redis.ttl(_live_track_key("recon-wbwin")) > gap, "live:track TTL must exceed the new-drive gap"
    assert await redis.ttl(_last_beat_key("recon-wbwin")) > gap

    # Simulate a ~45s drop: rewind last-beat 45s; both keys still alive (TTL 210s).
    cur = float(await redis.get(_last_beat_key("recon-wbwin")))
    await redis.set(_last_beat_key("recon-wbwin"), cur - 45.0)
    async with SessionLocal() as db:
        await device_service.set_offline(db, redis, "recon-wbwin")

    await _drive(device, redis, [(37.03, -122.0)])
    assert len(await get_live_track(redis, "recon-wbwin") or []) == 4, \
        "write-behind: a 45s reconnect (offline but not a new drive) must resume the Redis trail"
