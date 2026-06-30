"""Screenshot setup (LOCAL/dev only): make the sim device appear LIVE-DRIVING in Palo Alto near
xAI HQ (Page Mill Rd), with a blue trail, so the dashboard's 'Live location' hero renders for a README
screenshot. Mints a short-lived admin session and prints its cookie token to stdout. Run inside the
api container (it has the app + db + redis). NOT part of the product; nothing here ships to a device.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditEvent, Device, DeviceStatus, Session, User
from app.redis_client import mark_online
from app.security import generate_token, hash_token
from redis.asyncio import Redis
from sqlalchemy import delete, select

SIM_ALIAS = "Demo · Tesla Model 3"

# A REAL, road-following drive near xAI HQ, Palo Alto, that ENDS at xAI (1450 Page Mill Rd ≈
# 37.4140, -122.1500). Multiple waypoints so the blue trail winds through real streets with curves +
# turns (down toward El Camino, a loop through the neighborhood, back up Page Mill) — a believable
# drive, not one straight segment — with the final waypoint right at xAI HQ. OSRM stitches the actual
# street geometry through every waypoint.
XAI = (37.4149, -122.1491)  # 1450 Page Mill Rd — the drive lands here
# Matches the hand-drawn route: start WEST near Peter Coutts Rd, sweep DOWN the west side and around
# the BOTTOM, come UP the east side, WRAP across the top, then DESCEND from the top-right down to land
# at xAI HQ (final approach heading SW). Real street geometry for the big encircling on-map draw.
_WAYPOINTS = (
    "-122.1553,37.4152;"   # start WEST on Peter Coutts Road
    "-122.1500,37.4068;"   # down the west + around the bottom
    "-122.1448,37.4072;"   # bottom-east (Hillview/Porter area)
    "-122.1455,37.4140;"   # up the east side
    "-122.1440,37.4185;"   # wrap across the top (NE, Page Mill)
    "-122.1491,37.4149"    # DESCEND from the top down to xAI HQ (1450 Page Mill Rd)
)
_OSRM = (f"https://router.project-osrm.org/route/v1/driving/{_WAYPOINTS}"
         "?overview=full&geometries=geojson")


def _road_track() -> list[list[float]]:
    """[t, lat, lon] sampled along the real road geometry from OSRM (t = seconds since start at a
    steady ~13 m/s so timestamps look like a normal drive)."""
    with urllib.request.urlopen(_OSRM, timeout=20) as resp:
        data = json.load(resp)
    if data.get("code") != "Ok":
        sys.exit(f"OSRM routing failed: {data.get('code')} {data.get('message', '')}")
    coords = data["routes"][0]["geometry"]["coordinates"]  # [lon, lat] along the road
    pts: list[list[float]] = []
    t = 0.0
    for i, (lon, lat) in enumerate(coords):
        if i:
            plat, plon = pts[-1][1], pts[-1][2]
            dist = _haversine_m(plat, plon, lat, lon)
            t += dist / 13.0  # ~13 m/s ≈ 29 mph
        pts.append([round(t, 1), round(lat, 6), round(lon, 6)])
    return pts


def _haversine_m(la1: float, lo1: float, la2: float, lo2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(lo2 - lo1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, la2 = math.radians(a[0]), math.radians(b[0])
    dlo = math.radians(b[1] - a[1])
    y = math.sin(dlo) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlo)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


async def main() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    track = _road_track()
    # The drive ENDS at xAI HQ: arrow at the final point, the whole curvy path as trail behind it.
    cur_i = len(track) - 1
    cur = track[cur_i]
    heading = _bearing((track[cur_i - 1][1], track[cur_i - 1][2]), (cur[1], cur[2]))
    trail = [[p[1], p[2]] for p in track]  # [lat,lon] polyline of the entire driven path

    async with SessionLocal() as db:
        device = (
            await db.execute(select(Device).where(Device.is_simulated.is_(True)))
        ).scalars().first()
        if device is None:
            sys.exit("no simulated device found — create one via the dev tools first")
        device.alias = SIM_ALIAS
        device.platform = "Tesla Model 3"

        # Mark every OTHER device offline so only the demo driver appears in the shot.
        for other in (await db.execute(select(DeviceStatus))).scalars().all():
            if other.device_id != device.id:
                other.online = False
                other.onroad = False

        status = await db.get(DeviceStatus, device.id)
        if status is None:
            status = DeviceStatus(device_id=device.id)
            db.add(status)
        now = datetime.now(timezone.utc)
        status.online = True
        status.onroad = True
        status.last_heartbeat_at = now
        status.live_track = trail
        status.telemetry = {
            "captured_at": now.isoformat(),
            "onroad": True,
            "replaying": True,
            "subsystems": {
                "gps": {"status": "has_fix"},
                "driving": {
                    "speed_ms": 20.1,  # ~45 mph
                    "heading_deg": round(heading, 1),
                    "latitude": cur[1],
                    "longitude": cur[2],
                    "accuracy_m": 3.0,
                    "gear": "drive",
                },
                "thermal": {"status": "green", "max_c": 41.0},
                "software": {"version": "sunnypilot-2026.002.000-mypilot-2026.06.28",
                             "branch": "mypilot-mici"},
                "platform": {"name": "Tesla Model 3", "device_type": "comma 4"},
            },
        }

        # Make "Recent activity" read like real fleet activity (the dev DB is full of repetitive
        # replay events from testing). Replace it with a believable, varied set. The dashboard shows
        # only the humanized action + actor_type + relative time, so actor_id can stay None.
        await db.execute(delete(AuditEvent))
        demo_events = [
            ("device", "device.heartbeat", 1),
            ("user", "device.settings.update", 9),
            ("device", "route.upload.complete", 27),
            ("user", "device.software.update", 64),
            ("device", "device.online", 92),
            ("user", "device.pairing.claimed", 140),
        ]
        for actor_type, action, mins_ago in demo_events:
            db.add(AuditEvent(actor_type=actor_type, actor_id=None, action=action,
                              device_id=device.id if actor_type == "device" else None,
                              event_metadata={}, created_at=now - timedelta(minutes=mins_ago)))

        # Mint a screenshot admin session.
        admin = (await db.execute(select(User).where(User.is_admin.is_(True)))).scalars().first()
        if admin is None:
            sys.exit("no admin user")
        raw = generate_token()
        db.add(Session(
            user_id=admin.id,
            token_hash=hash_token(raw),
            csrf_token=generate_token(),
            expires_at=now + timedelta(hours=2),
        ))
        await db.commit()
        dev_id = device.id

    # Clear presence for every other device so only the demo driver is "online" in the shot.
    for key in await redis.keys("presence:device:*"):
        if not key.endswith(dev_id):
            await redis.delete(key)
    # Generous presence so the hero stays live long enough to capture (TTL default is only 30s).
    await mark_online(redis, dev_id, 3600)
    await redis.aclose()

    print(f"SESSION_TOKEN={raw}")
    print(f"DEVICE_ID={dev_id}")
    print(f"POSITION={cur[1]},{cur[2]} heading={round(heading,1)} trail_points={len(trail)}")


if __name__ == "__main__":
    asyncio.run(main())
