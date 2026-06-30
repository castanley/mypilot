"""The accumulating live-trail helper: appends while moving, drops jitter, clears offroad, bounded."""

from __future__ import annotations

from app.device_service import _LIVE_TRACK_MAX, _LIVE_TRACK_SIMPLIFY_AT, update_live_track
from app.models import DeviceStatus


def _st() -> DeviceStatus:
    return DeviceStatus(device_id="d", live_track=None)


def test_appends_points_while_moving():
    s = _st()
    update_live_track(s, True, {"latitude": 37.0, "longitude": -122.0})
    update_live_track(s, True, {"latitude": 37.001, "longitude": -122.0})  # ~111m north
    assert s.live_track == [[37.0, -122.0], [37.001, -122.0]]


def test_drops_jitter_below_min_move():
    s = _st()
    update_live_track(s, True, {"latitude": 37.0, "longitude": -122.0})
    # ~2m away — below the 8m gate, so it must NOT append a second point.
    update_live_track(s, True, {"latitude": 37.00002, "longitude": -122.0})
    assert s.live_track == [[37.0, -122.0]]


def test_clears_when_offroad():
    s = _st()
    update_live_track(s, True, {"latitude": 37.0, "longitude": -122.0})
    update_live_track(s, False, None)
    assert s.live_track is None


def test_ignores_missing_fix():
    s = _st()
    update_live_track(s, True, {"latitude": None, "longitude": None})
    update_live_track(s, True, None)
    assert not s.live_track  # None or empty — nothing appended without a fix


def test_straight_drive_is_simplified_not_huge():
    """A long, near-straight drive must stay FAR smaller than its raw point count — simplification (at
    the ceiling) collapses straight runs so size tracks SHAPE, not duration. Keeps long drives light."""
    s = _st()
    n = 4000  # crosses the 1500 simplify ceiling more than twice
    for i in range(n):  # ~straight north
        update_live_track(s, True, {"latitude": 37.0 + i * 0.001, "longitude": -122.0})
    # Each time it hits the ceiling the straight line collapses to ~2; it never approaches n.
    assert len(s.live_track) < n // 2
    # End of the trail is still the latest position.
    assert s.live_track[-1][0] == round(37.0 + (n - 1) * 0.001, 6)


def test_curvy_drive_keeps_detail_and_stays_bounded():
    """A winding drive keeps its shape (not collapsed like a straight line) yet stays bounded by the
    simplify ceiling — and simplification runs occasionally, not every append (kept fast)."""
    import math
    s = _st()
    for i in range(_LIVE_TRACK_SIMPLIFY_AT + 200):
        # A sine-wave road: genuinely curvy, so simplification can't collapse it to a few points.
        lat = 37.0 + i * 0.0009
        lon = -122.0 + 0.01 * math.sin(i / 5.0)
        update_live_track(s, True, {"latitude": lat, "longitude": lon})
    assert len(s.live_track) <= _LIVE_TRACK_MAX
    assert len(s.live_track) > 100  # detail preserved (not collapsed like a straight line)
