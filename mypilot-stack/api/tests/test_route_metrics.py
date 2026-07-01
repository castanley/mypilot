"""route_metrics: derive duration_s/distance_m from the stored GPS track (no qlog).

The device doesn't send duration/distance, and there's no server-side qlog parser — so route_complete
derives them from the [t, lat, lon] polyline it already stores. These pin the pure helper plus the
integration (a route completed WITHOUT device-supplied metrics gets them filled; a route WITH them
keeps the device's values)."""

from __future__ import annotations

from app.geocode import nearest_city
from app.routes_service import _haversine_m, route_metrics

from .helpers import device_post, device_put, pair_device, setup_admin

# --- pure helper -------------------------------------------------------------------------------

def test_route_metrics_from_track():
    # ~1 km north over 100 s: 0.009 deg lat ≈ 1001 m.
    track = [[0.0, 37.0, -122.0], [50.0, 37.0045, -122.0], [100.0, 37.009, -122.0]]
    dur, dist = route_metrics(track, segment_count=2)
    assert dur == 100
    assert 950 <= dist <= 1050  # ~1 km


def test_route_metrics_empty_track_falls_back_to_segments():
    # No usable track → duration from segment_count*60, distance unknowable (None).
    assert route_metrics(None, segment_count=3) == (180, None)
    assert route_metrics([], segment_count=0) == (None, None)
    assert route_metrics([[0.0, 37.0, -122.0]], segment_count=5) == (300, None)  # single point


def test_route_metrics_skips_garbage_points():
    track = [
        [0.0, 37.0, -122.0],
        ["bad", 1, 2],                 # non-numeric t
        [10.0, 999.0, -122.0],         # out-of-range lat
        [20.0, 37.001, -122.0],
    ]
    dur, dist = route_metrics(track, segment_count=1)
    assert dur == 20  # last VALID point's t
    assert dist is not None and dist > 0  # computed over the surviving in-range points


def test_haversine_zero_and_known():
    assert _haversine_m(37.0, -122.0, 37.0, -122.0) == 0.0
    # ~111 m for 0.001 deg latitude.
    assert 100 <= _haversine_m(37.0, -122.0, 37.001, -122.0) <= 120


# --- integration: route_complete derives metrics when the device didn't send them --------------

async def _start_and_upload(client, device_id, keys, name, body, extra_start=None):
    payload = {"name": name, "segment_count": 1,
               "files": [{"segment_index": 0, "name": "qlog.zst", "kind": "qlog"}]}
    if extra_start:
        payload.update(extra_start)
    r = await device_post(client, device_id, keys, "/api/ingest/routes/start", payload)
    rid = r.json()["route_id"]
    await device_put(client, device_id, keys, f"/api/ingest/routes/{rid}/files/0/qlog.zst", body)
    return rid


async def test_complete_derives_metrics_from_track_when_device_omits(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    # Device sends a track but NO duration_s/distance_m (the real-device case).
    track = [[0.0, 37.0, -122.0], [120.0, 37.009, -122.0]]  # ~1 km over 120 s
    rid = await _start_and_upload(client, device_id, keys, "2026-07-01--10-00-00", b"q" * 64,
                                  extra_start={"track": track})
    await device_post(client, device_id, keys, f"/api/ingest/routes/{rid}/complete", {})
    detail = (await client.get(f"/api/routes/{rid}")).json()
    assert detail["duration_s"] == 120           # from the track's last t
    assert 950 <= detail["distance_m"] <= 1050   # ~1 km haversine


async def test_complete_keeps_device_supplied_metrics(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    # Device DID send duration/distance → must NOT be overwritten by the derived values.
    track = [[0.0, 37.0, -122.0], [120.0, 37.009, -122.0]]
    rid = await _start_and_upload(client, device_id, keys, "2026-07-01--11-00-00", b"q" * 64,
                                  extra_start={"track": track, "duration_s": 999, "distance_m": 42.0})
    await device_post(client, device_id, keys, f"/api/ingest/routes/{rid}/complete", {})
    detail = (await client.get(f"/api/routes/{rid}")).json()
    assert detail["duration_s"] == 999
    assert detail["distance_m"] == 42.0


# --- backfill maintenance endpoint (admin, metadata-only, reversible) --------------------------

async def test_backfill_fills_missing_metrics_from_track(client):
    """A pre-existing route with a track but NULL duration/distance (the fleet-wide state) gets them
    filled by the backfill endpoint; already-filled routes are untouched; re-running is idempotent."""
    from app.db import SessionLocal
    from app.models import Route

    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    # Create a route via ingest, then null-out its metrics to simulate the legacy fleet state.
    track = [[0.0, 37.0, -122.0], [200.0, 37.018, -122.0]]  # ~2 km over 200 s
    rid = await _start_and_upload(client, device_id, keys, "2026-07-01--12-00-00", b"q" * 64,
                                  extra_start={"track": track})
    await device_post(client, device_id, keys, f"/api/ingest/routes/{rid}/complete", {})
    async with SessionLocal() as db:
        r = await db.get(Route, rid)
        r.duration_s = None
        r.distance_m = None
        await db.commit()

    # Backfill (admin + CSRF).
    resp = await client.post("/api/maintenance/backfill-route-metrics", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200, resp.text
    assert resp.json()["routes_updated"] >= 1

    detail = (await client.get(f"/api/routes/{rid}")).json()
    assert detail["duration_s"] == 200
    assert 1900 <= detail["distance_m"] <= 2100

    # Idempotent: a second run updates nothing new for this route.
    again = await client.post("/api/maintenance/backfill-route-metrics", headers={"X-CSRF-Token": csrf})
    assert again.status_code == 200


async def test_backfill_requires_admin(app):
    """The backfill maintenance endpoint is admin-only (require_csrf + is_admin). A non-admin user
    must get 403 — a metadata sweep over every route is not a regular-user action."""
    from app.db import SessionLocal
    from app.models import User
    from app.security import hash_password
    from httpx import ASGITransport, AsyncClient, Cookies

    # First user = admin (setup); then a plain non-admin.
    await setup_admin(AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=Cookies()))
    async with SessionLocal() as db:
        db.add(User(username="plainuser", password_hash=hash_password("plain-pass-123"), is_admin=False))
        await db.commit()
    cu = AsyncClient(transport=ASGITransport(app=app), base_url="http://test", cookies=Cookies())
    login = await cu.post("/api/auth/login", json={"username": "plainuser", "password": "plain-pass-123"})
    csrf = login.json()["csrf_token"]
    try:
        r = await cu.post("/api/maintenance/backfill-route-metrics", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 403, f"non-admin must be 403, got {r.status_code}"
    finally:
        await cu.aclose()


# --- offline reverse geocode (FEATURE-MAP-CITIES) ----------------------------------------------

def test_nearest_city_offline():
    # A known coordinate resolves to the right city, entirely offline (bundled dataset).
    assert nearest_city(37.7749, -122.4194) == "San Francisco, CA"   # US → "City, ST"
    assert nearest_city(40.7128, -74.0060, max_km=50) is not None      # NYC resolves
    # No fix / garbage / open ocean → None (never a bogus far-away city).
    assert nearest_city(None, None) is None
    assert nearest_city(999, 0) is None
    assert nearest_city(0.0, -160.0) is None  # mid-Pacific, nothing within max_km


async def test_complete_geocodes_start_end_city(client):
    """route_complete fills start/end city from the track endpoints via the offline dataset — shown
    on the /map tile as 'City → City'. Start and end are geocoded independently."""
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    # SF → NYC (endpoints only; the middle points don't matter for city resolution).
    track = [[0.0, 37.7749, -122.4194], [3600.0, 40.7128, -74.0060]]
    rid = await _start_and_upload(client, device_id, keys, "2026-07-01--13-00-00", b"q" * 64,
                                  extra_start={"track": track})
    await device_post(client, device_id, keys, f"/api/ingest/routes/{rid}/complete", {})
    detail = (await client.get(f"/api/routes/{rid}")).json()
    assert detail["start_location"] == "San Francisco, CA"
    assert detail["end_location"] and "New York" in detail["end_location"]
    # And the fields are on the SUMMARY (map tile), not just detail.
    summary = [r for r in (await client.get("/api/routes")).json() if r["id"] == rid][0]
    assert summary["start_location"] == "San Francisco, CA"


async def test_backfill_fills_cities_too(client):
    """The single backfill pass fills duration+distance AND start/end city on an existing route that
    has a track but null metadata (the fleet-wide legacy state)."""
    from app.db import SessionLocal
    from app.models import Route

    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)
    track = [[0.0, 37.7749, -122.4194], [1200.0, 37.8044, -122.2712]]  # SF → Oakland
    rid = await _start_and_upload(client, device_id, keys, "2026-07-01--14-00-00", b"q" * 64,
                                  extra_start={"track": track})
    await device_post(client, device_id, keys, f"/api/ingest/routes/{rid}/complete", {})
    async with SessionLocal() as db:
        r = await db.get(Route, rid)
        r.duration_s = r.distance_m = r.start_location = r.end_location = None
        await db.commit()

    resp = await client.post("/api/maintenance/backfill-route-metrics", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 200 and resp.json()["routes_updated"] >= 1
    detail = (await client.get(f"/api/routes/{rid}")).json()
    assert detail["duration_s"] == 1200
    assert detail["distance_m"] is not None
    assert detail["start_location"] == "San Francisco, CA"
    assert detail["end_location"] is not None

