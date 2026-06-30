"""Regression tests for GPS track extraction — the bug where most trips drew no line because their
track truncated to the first 60s segment (or 1/0 points). Covers the three confirmed mechanisms:

  1. multi-segment tracks must span PAST the first 60s segment (not clip at the boundary);
  2. a segment with GPS fixes but NO encode-index frames must still yield points (wall-clock fallback);
  3. a moving segment whose GNSS `speed` field is ABSENT must yield >1 point (derived-speed fallback),
     while a genuinely parked segment still collapses (jitter suppression preserved).

We inject a fake `openpilot.tools.lib.logreader.LogReader` via sys.modules so the device-only import
resolves in CI (no openpilot/cereal installed).
"""

from __future__ import annotations

import sys
import types

from mypilot_agent import drive_video

_SEG = drive_video._SEGMENT_SECONDS  # 60.0


class _Msg:
    """A fake cereal message: which() + the union accessor + logMonoTime."""

    def __init__(self, kind: str, mono_s: float, **fields):
        self._kind = kind
        self.logMonoTime = int(mono_s * 1e9)
        self._val = types.SimpleNamespace(**fields)

    def which(self):
        return self._kind

    def __getattr__(self, name):
        # msg.<kind> returns the union value (e.g. msg.gpsLocation)
        if name == self.__dict__.get("_kind"):
            return self.__dict__["_val"]
        raise AttributeError(name)


def _gps(mono_s, lat, lon, *, speed=0.0, has_fix=True, with_speed=True):
    fields = {"hasFix": has_fix, "latitude": lat, "longitude": lon}
    if with_speed:
        fields["speed"] = speed
    return _Msg("gpsLocation", mono_s, **fields)


def _encode(mono_s, seg_num, seg_id):
    return _Msg("qRoadEncodeIdx", mono_s, segmentNum=seg_num, segmentId=seg_id)


def _install_fake_logreader(monkeypatch, by_path: dict[str, list]):
    """Route LogReader(path) -> the canned message list for that path."""
    mod_lr = types.ModuleType("openpilot.tools.lib.logreader")

    class LogReader:
        def __init__(self, path):
            self._msgs = by_path[path]

        def __iter__(self):
            return iter(self._msgs)

    mod_lr.LogReader = LogReader
    # Build the package chain openpilot.tools.lib.logreader so the lazy import resolves.
    for name in ("openpilot", "openpilot.tools", "openpilot.tools.lib"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "openpilot.tools.lib.logreader", mod_lr)
    # extract_route_track reads files off disk; make every candidate path "exist" and map qlog->msgs.
    monkeypatch.setattr(drive_video.os.path, "isfile", lambda p: p in by_path)


def _seg_path(route, seg):
    return drive_video.os.path.join(drive_video.REALDATA, f"{route}--{seg}", "qlog.zst")


def _moving_segment(seg_num, *, with_speed=True, speed=10.0):
    """A 60s segment with encode frames + ~moving GPS fixes (advancing north each second)."""
    base = seg_num * 100.0  # arbitrary mono base, distinct per segment
    msgs = []
    for i in range(60):
        msgs.append(_encode(base + i, seg_num, i * drive_video._VIDEO_FPS))
        msgs.append(_gps(base + i, 37.5 + (seg_num * 60 + i) * 0.0003, -122.3,
                         speed=speed, with_speed=with_speed))
    return msgs


def test_multi_segment_track_spans_past_first_segment(monkeypatch):
    route = "00000000--aaaaaaaaaa"
    by_path = {_seg_path(route, s): _moving_segment(s) for s in range(3)}
    _install_fake_logreader(monkeypatch, by_path)

    track = drive_video.extract_route_track(route, {0: [], 1: [], 2: []})
    assert track, "expected a non-empty track"
    max_t = max(p[0] for p in track)
    assert max_t > _SEG, f"track clipped at the first segment (max t={max_t}) — the truncation bug"
    assert max_t > 2 * _SEG, "track should reach into the third segment"


def test_segment_without_encode_frames_still_yields_points(monkeypatch):
    """The 0-point bucket: a segment with fixes but no encode-index frames must use the wall-clock
    fallback rather than dropping every fix."""
    route = "00000005--bbbbbbbbbb"
    # GPS fixes only, NO _encode() messages.
    msgs = [_gps(i, 37.5 + i * 0.0003, -122.3, speed=10.0) for i in range(30)]
    by_path = {_seg_path(route, 0): msgs}
    _install_fake_logreader(monkeypatch, by_path)

    track = drive_video.extract_route_track(route, {0: []})
    assert len(track) > 1, "no-encode-frame segment dropped all fixes (the 0-point bug)"


def test_missing_speed_field_moving_yields_many_points(monkeypatch):
    """The 1-point bucket: GNSS `speed` field absent but the car is clearly moving -> derived speed
    must keep the points instead of treating everything as stationary."""
    route = "00000002--cccccccccc"
    by_path = {_seg_path(route, 0): _moving_segment(0, with_speed=False)}
    _install_fake_logreader(monkeypatch, by_path)

    track = drive_video.extract_route_track(route, {0: []})
    assert len(track) > 1, "missing-speed moving segment collapsed to <=1 point (the 1-point bug)"


def test_parked_segment_still_collapses(monkeypatch):
    """Jitter suppression preserved: a stationary segment (no real movement, no speed field) must NOT
    draw a scribble — it collapses to ~1 anchor point."""
    route = "00000009--dddddddddd"
    # 30 fixes all within ~1m, speed field absent -> derived speed ~0.
    msgs = []
    for i in range(30):
        msgs.append(_encode(i, 0, i * drive_video._VIDEO_FPS))
        msgs.append(_gps(i, 37.50000 + (i % 2) * 0.000002, -122.3, with_speed=False))
    by_path = {_seg_path(route, 0): msgs}
    _install_fake_logreader(monkeypatch, by_path)

    track = drive_video.extract_route_track(route, {0: []})
    assert len(track) <= 2, f"parked car drew a scribble ({len(track)} pts) — jitter suppression broke"


def test_stationary_fixes_with_speed_field_drop(monkeypatch):
    """The original behavior: explicit near-zero speed still drops stationary fixes."""
    route = "0000000a--eeeeeeeeee"
    msgs = []
    for i in range(30):
        msgs.append(_encode(i, 0, i * drive_video._VIDEO_FPS))
        msgs.append(_gps(i, 37.5 + i * 0.0003, -122.3, speed=0.0))  # speed present, ~0
    by_path = {_seg_path(route, 0): msgs}
    _install_fake_logreader(monkeypatch, by_path)

    track = drive_video.extract_route_track(route, {0: []})
    assert len(track) == 1, "explicit zero-speed fixes should collapse to the single anchor point"
