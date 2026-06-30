"""status_dict() is the ONE place device liveness is decided. These pin the presence clamp so a
future read site can't reintroduce a stale-onroad/driving path (the "phantom live map" bug class).

The clamp's defining property: status.online (the raw DB column) is NEVER what reaches the wire —
`online` is always the authoritative Redis presence passed in by the caller, and an offline device
is force-parked here (onroad False, driving mirror dropped, trail emptied, replaying cleared)."""

from __future__ import annotations

from app.device_service import status_dict
from app.models import DeviceStatus


def _driving_status() -> DeviceStatus:
    # A row that looks "live" at the DB level: online True, onroad True, with a driving fix + trail.
    return DeviceStatus(
        device_id="d1",
        online=True,
        onroad=True,
        telemetry={
            "onroad": True,
            "replaying": True,
            "subsystems": {"driving": {"latitude": 1.0, "longitude": 2.0, "speed_ms": 20.0}},
        },
        live_track=[[1.0, 2.0], [1.1, 2.1]],
    )


def test_offline_is_force_parked():
    """Redis says gone -> everything live is cleared, regardless of the DB columns saying otherwise."""
    d = status_dict(_driving_status(), online=False)
    assert d["online"] is False
    assert d["onroad"] is False
    assert d["replaying"] is False
    assert d["subsystems"]["driving"] is None  # live position mirror dropped
    assert d["live_track"] == []               # trail not served for a parked/offline device


def test_online_onroad_passes_through():
    """An actually-online onroad device keeps its live telemetry (no regression to the live map)."""
    d = status_dict(_driving_status(), online=True)
    assert d["online"] is True
    assert d["onroad"] is True
    assert d["replaying"] is True
    assert d["subsystems"]["driving"]["latitude"] == 1.0
    assert d["live_track"] == [[1.0, 2.0], [1.1, 2.1]]


def test_online_but_offroad_drops_driving():
    """Online but parked (onroad False): no live position/trail, but still reported online."""
    s = _driving_status()
    s.onroad = False
    d = status_dict(s, online=True)
    assert d["online"] is True
    assert d["onroad"] is False
    assert d["subsystems"]["driving"] is None
    assert d["live_track"] == []


def test_never_emits_raw_db_online():
    """The raw DB column must never be what's served: online=True row, Redis says offline -> offline."""
    s = _driving_status()
    s.online = True  # stale DB column
    assert status_dict(s, online=False)["online"] is False
