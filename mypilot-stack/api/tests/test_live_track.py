"""The accumulating live-trail helper: appends while moving, drops jitter, clears offroad, bounded."""

from __future__ import annotations

import pytest
from app.device_service import (
    _LIVE_TRACK_MAX,
    _LIVE_TRACK_SIMPLIFY_AT,
    _LIVE_TRACK_TOL_MAX_M,
    _finite_point,
    _next_live_track,
    _next_live_track_async,
    update_live_track,
)
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
    """A long, near-straight drive must stay FAR smaller than its raw point count — simplification
    collapses straight runs so size tracks SHAPE, not duration. Feed exactly one accumulation band
    (MAX + SIMPLIFY_AT) so exactly one simplify fires: a perfectly straight line Douglas-Peucker's down
    to its two endpoints, so the stored trail must end up tiny despite thousands of raw appends."""
    s = _st()
    n = _LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT  # exactly the band → the last append triggers simplify
    for i in range(n):  # ~straight north
        update_live_track(s, True, {"latitude": 37.0 + i * 0.001, "longitude": -122.0})
    # A straight line collapses to a handful of points (endpoints), nowhere near n.
    assert len(s.live_track) < 100
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
    assert len(s.live_track) <= _LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT
    assert len(s.live_track) > 100  # detail preserved (not collapsed like a straight line)


def test_long_curvy_drive_keeps_whole_route_not_just_the_tail():
    """A multi-hour very-curvy drive must keep its FULL shape end-to-end (escalating simplification),
    NOT truncate the start to the last N points. The first point must remain near the drive's start."""
    import math
    s = _st()
    start_lat, start_lon = 37.0, -122.0
    # A long, genuinely curvy drive (broad sweeping curves like a winding highway — not a per-point
    # zigzag) with enough points that even a base-tolerance simplify exceeds the ceiling, forcing the
    # escalation path. Realistic shape so simplification behaves like it does on real GPS.
    n = 12000
    for i in range(n):
        lat = start_lat + i * 0.0004
        lon = start_lon + 0.03 * math.sin(i / 60.0)
        update_live_track(s, True, {"latitude": lat, "longitude": lon})
    assert len(s.live_track) <= _LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT  # still bounded (amortized cap)
    # The START of the drive is retained (escalating simplify, not tail-truncation): the first kept
    # point is at/near the real start, NOT thousands of points in.
    assert s.live_track[0][0] == round(start_lat, 6)
    # And the end is still the latest position — full span preserved.
    assert abs(s.live_track[-1][0] - round(start_lat + (n - 1) * 0.0004, 6)) < 1e-6


def test_incompressible_track_bounded_and_hot_path_stays_fast():
    """PERF (hot path): a near-incompressible/noisy track resists every escalated tolerance. Two things
    must hold: (1) the stored trail stays BOUNDED (amortized cap = MAX + one SIMPLIFY_AT batch, then the
    hard-cap backstop after escalation exhausts), and (2) it must NOT re-run the O(n^2) simplify on
    every beat — that would stall the synchronous, on-event-loop heartbeat path fleet-wide. We assert
    the amortized cost: many beats at the ceiling complete well under a per-beat budget."""
    import random
    import time
    s = _st()
    rng = random.Random(1)
    # Prime to steady-state well past the cap so subsequent beats are the pathological "at ceiling" case.
    for _ in range(_LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT + 100):
        update_live_track(s, True, {"latitude": 37.0 + rng.uniform(-0.5, 0.5),
                                    "longitude": -122.0 + rng.uniform(-0.5, 0.5)})
    assert len(s.live_track) <= _LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT  # bounded

    # Now time a window LONG ENOUGH to cross the re-simplify trigger at least once (it takes a full
    # SIMPLIFY_AT batch of appends to climb from the capped MAX back up to the trigger). This makes the
    # measurement a true AMORTIZED cost — it includes the O(n^2) escalation spike, spread over the batch
    # of cheap appends that earned it. With the old per-beat-simplify bug this window re-ran the full
    # escalation on EVERY beat (~20ms each → the window would take tens of seconds); amortized it must
    # stay far cheaper. Budget generously (CI is slow and shared): < 5ms/beat averaged.
    beats = 2 * _LIVE_TRACK_SIMPLIFY_AT  # guarantees the trigger is crossed (and re-simplified) >= once
    t0 = time.perf_counter()
    for _ in range(beats):
        update_live_track(s, True, {"latitude": 37.0 + rng.uniform(-0.5, 0.5),
                                    "longitude": -122.0 + rng.uniform(-0.5, 0.5)})
    per_beat_ms = (time.perf_counter() - t0) / beats * 1000
    assert len(s.live_track) <= _LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT
    assert per_beat_ms < 5.0, f"hot path too slow: {per_beat_ms:.1f}ms/beat (per-beat simplify stall?)"


# --- Coordinate validation: a non-finite / out-of-range fix must never reach the trail geometry. ---
# Left unguarded these are a live per-device DoS: an inf tail makes _coarse_far do math.cos(inf) ->
# ValueError, crashing the heartbeat every subsequent beat; a NaN seed makes every jitter-gate
# comparison False, so no real fix ever appends (frozen trail). The ingest schema rejects them at the
# boundary; the accumulator ALSO defends itself so a trail rehydrated from Redis/DB (predating the
# validator) self-heals.

@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), 91.0, -90.001])
def test_incoming_bad_latitude_is_dropped(bad):
    s = _st()
    update_live_track(s, True, {"latitude": 37.0, "longitude": -122.0})
    before = list(s.live_track)
    update_live_track(s, True, {"latitude": bad, "longitude": -122.0})
    assert s.live_track == before  # bad point dropped, trail unchanged


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), 181.0])
def test_incoming_bad_longitude_is_dropped(bad):
    s = _st()
    update_live_track(s, True, {"latitude": 37.0, "longitude": bad})
    assert not s.live_track  # nothing appended from a bad first fix


def test_poisoned_inf_tail_does_not_crash_and_self_heals():
    """A trail rehydrated from Redis/DB with a non-finite TAIL (legacy, pre-validator) must not raise on
    the next beat (the old crash vector: _coarse_far -> math.cos(inf) -> ValueError) and must purge the
    poison so the trail keeps accumulating."""
    s = DeviceStatus(device_id="d", live_track=[[37.0, -122.0], [float("inf"), -122.0]])
    update_live_track(s, True, {"latitude": 37.01, "longitude": -122.0})  # must not raise
    assert all(_finite_point(p) for p in s.live_track)
    assert [37.01, -122.0] in s.live_track


def test_nan_seeded_trail_unfreezes():
    """A NaN first point used to freeze the trail (every _coarse_far comparison is False). After the
    guard, real fixes append again and the NaN is purged."""
    s = DeviceStatus(device_id="d", live_track=[[float("nan"), -122.0]])
    appended = 0
    for i in range(5):
        before = len(s.live_track or [])
        update_live_track(s, True, {"latitude": 37.0 + i * 0.01, "longitude": -122.0})
        if len(s.live_track) > before:
            appended += 1
    assert appended >= 3  # was 0/5 before the fix (frozen)
    assert all(_finite_point(p) for p in s.live_track)


@pytest.mark.parametrize("bad_idx", [0, 1, 50])
def test_interior_or_head_poison_does_not_crash_simplify(bad_idx):
    """A rehydrated trail whose poison is NOT the tail (finite tail, so the O(1) tail guard doesn't fire)
    must still not crash when it crosses the simplify trigger: _simplify_escalate does math.cos on the
    coords, so a lingering inf/NaN would raise math-domain there. It's scrubbed defensively at the
    simplify entry. (This is the SB-C regression: the tail-only self-heal missed interior/head poison.)"""
    band = _LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT
    trail = [[37.0 + i * 1e-4, -122.0] for i in range(band - 1)]
    trail[bad_idx] = [float("inf"), -122.0]  # finite tail, poison earlier — trigger fires on next append
    out = _next_live_track(trail, True, {"latitude": 38.0, "longitude": -122.5})  # must not raise
    assert out is not None
    assert all(_finite_point(p) for p in out)
    assert len(out) <= _LIVE_TRACK_MAX


def test_simplify_escalate_scrubs_non_finite_defensively():
    """_simplify_escalate is the last line of defense: even handed a poisoned trail directly (e.g. from a
    corrupt Redis blob past the append guards) it must scrub and never raise."""
    from app.device_service import _simplify_escalate
    poisoned = [[37.0, -122.0], [float("inf"), -122.0], [37.1, -122.0], [float("nan"), -122.0]] * 2000
    out = _simplify_escalate(poisoned)
    assert all(_finite_point(p) for p in out)
    assert len(out) <= _LIVE_TRACK_MAX


def test_finite_point_helper():
    assert _finite_point([37.0, -122.0])
    assert not _finite_point([float("nan"), -122.0])
    assert not _finite_point([37.0, float("inf")])
    assert not _finite_point([37.0])          # wrong arity
    assert not _finite_point([200.0, -122.0])  # out of range
    assert not _finite_point("nope")           # wrong type
    assert not _finite_point([None, -122.0])   # non-numeric


# --- Event-loop safety: the O(n^2) simplify must run OFF the shared loop on the hot path. ---
# Douglas-Peucker is worst-case O(n^2); an adversarial "sawtooth" trail (every point a local extreme,
# reachable by any authenticated device) makes a single pass take multiple SECONDS at the trigger size.
# On the single uvicorn loop that freezes EVERY device's heartbeat/WS for that whole time, so
# apply_heartbeat uses _next_live_track_async, which offloads _simplify_escalate via asyncio.to_thread.

def _straight(n: int) -> list:
    """A trail that simplifies FAST (a straight line DP-collapses to its endpoints). Still fires the
    trigger at n >= band, so it exercises the simplify path without the multi-second adversarial cost."""
    return [[37.0 + i * 1e-4, -122.0] for i in range(n)]


@pytest.mark.asyncio
async def test_async_offload_keeps_event_loop_responsive_under_slow_simplify(monkeypatch):
    """The hot-path variant must offload the simplify so a slow pass can't freeze the shared loop.

    We isolate the OFFLOAD MECHANISM (not the real DP cost): stub _simplify_escalate with a bounded
    CPU spin (~0.3s), then run _next_live_track_async concurrently with a ticker. If the simplify ran
    ON the loop, the ticker would starve for the whole spin; because it's dispatched via
    asyncio.to_thread, the loop keeps servicing the ticker (a Python CPU loop still yields the GIL
    periodically). Fast enough for CI, yet unambiguous — an on-loop regression pushes the gap to ~0.3s."""
    import asyncio
    import time

    from app import device_service

    def _slow_stub(track):
        end = time.perf_counter() + 0.3  # bounded CPU-bound work, NOT time.sleep (which would cheat)
        x = 0
        while time.perf_counter() < end:
            x += 1
        return track[-_LIVE_TRACK_MAX:] if len(track) > _LIVE_TRACK_MAX else track

    monkeypatch.setattr(device_service, "_simplify_escalate", _slow_stub)

    gaps: list[float] = []
    stop = False

    async def ticker():
        last = time.perf_counter()
        while not stop:
            await asyncio.sleep(0)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    tk = asyncio.create_task(ticker())
    await asyncio.sleep(0.05)  # let the ticker settle
    band = _LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT
    result = await device_service._next_live_track_async(_straight(band - 1), True,
                                                         {"latitude": 38.0, "longitude": -122.5})
    stop = True
    await asyncio.sleep(0.01)
    tk.cancel()

    assert len(result) <= _LIVE_TRACK_MAX  # the (stubbed) simplify actually ran
    max_gap_ms = (max(gaps) if gaps else 0.0) * 1000
    # Offloaded: the loop keeps ticking (gap ~ a scheduler slice). On-loop it would be ~300ms.
    assert max_gap_ms < 150, f"event loop stalled {max_gap_ms:.0f}ms during simplify (offload broken?)"


@pytest.mark.asyncio
async def test_async_matches_sync_result():
    """The offloaded hot-path variant must produce the identical trail to the sync path (all branches:
    a trigger-firing drive, an offroad/absent fix, and a rejected non-finite fix)."""
    band = _LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT
    for base, onroad, drive in (
        (_straight(band - 1), True, {"latitude": 38.0, "longitude": -122.5}),  # fires simplify
        (_straight(10), True, {"latitude": None, "longitude": None}),          # no fix -> unchanged
        (_straight(10), False, None),                                          # offroad -> cleared
        (_straight(10), True, {"latitude": float("inf"), "longitude": -122.0}),  # bad fix -> dropped
    ):
        assert _next_live_track(list(base), onroad, drive) == \
            await _next_live_track_async(list(base), onroad, drive)


def test_escalation_terminates_and_bounds_incompressible_at_max():
    """A genuinely incompressible trail: once the simplify fires, the stored trail is bounded <= MAX by
    the escalation + hard-cap, and the escalation loop always terminates (tolerance bounded by TOL_MAX).
    Uses a pseudo-random walk (incompressible but fast to simplify — no adversarial O(n^2) blowup)."""
    import random
    rng = random.Random(7)
    band = _LIVE_TRACK_MAX + _LIVE_TRACK_SIMPLIFY_AT
    trail = [[37.0 + rng.uniform(-0.4, 0.4), -122.0 + rng.uniform(-0.4, 0.4)] for _ in range(band - 1)]
    out = _next_live_track(trail, True, {"latitude": 38.0, "longitude": -122.5})
    assert len(out) <= _LIVE_TRACK_MAX
    assert _LIVE_TRACK_TOL_MAX_M > 0  # the bound the while-loop relies on to terminate
