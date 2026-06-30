"""Route GPS track is monotonically improvable across re-declares.

The bug: a drive uploads across several offroad cycles; an early cycle could store a partial track
(e.g. only the first 60s segment), and `route_start` previously backfilled only when gps_track was
null — so the later, complete track was silently rejected and most trips showed a track truncated at
the first segment. The fix: adopt a track only when it's FULLER, never shrink. These pin that.
"""

from __future__ import annotations

from .helpers import device_post, pair_device, setup_admin

ROUTE = "2026-06-28--10-00-00"


def _track(n: int) -> list[list[float]]:
    # n points marching north from a fixed origin; t = seconds.
    return [[float(i), 37.5 + i * 0.0005, -122.3] for i in range(n)]


async def _declare(client, device_id, keys, track):
    r = await device_post(
        client, device_id, keys, "/api/ingest/routes/start",
        {"name": ROUTE, "segment_count": 1,
         "files": [{"segment_index": 0, "name": "qlog.zst", "kind": "qlog"}],
         "track": track},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_fuller_track_replaces_partial(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)

    # 1) early cycle: a 1-point partial track (the truncation symptom).
    first = await _declare(client, device_id, keys, _track(1))
    assert first["track_points"] == 1
    route_id = first["route_id"]

    # 2) later cycle: the full 530-point track for the same route -> must be adopted.
    second = await _declare(client, device_id, keys, _track(530))
    assert second["track_points"] == 530
    assert second["route_id"] == route_id  # same route, not a duplicate

    track = (await client.get(f"/api/routes/{route_id}/track")).json()["track"]
    assert len(track) == 530


async def test_shorter_track_never_shrinks(client):
    csrf = await setup_admin(client)
    device_id, keys = await pair_device(client, csrf)

    full = await _declare(client, device_id, keys, _track(530))
    assert full["track_points"] == 530
    route_id = full["route_id"]

    # A later track-less or partial re-declare must NOT wipe/shrink the good track.
    again = await _declare(client, device_id, keys, _track(1))
    assert again["track_points"] == 530  # unchanged

    none_track = await _declare(client, device_id, keys, None)
    assert none_track["track_points"] == 530

    track = (await client.get(f"/api/routes/{route_id}/track")).json()["track"]
    assert len(track) == 530
