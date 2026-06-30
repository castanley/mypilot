"""Device telemetry envelope — the shared contract between the agent (producer) and the Stack
(consumer) for the WebSocket STATUS frame body.

The STATUS frame stays ``{"type": "status", "payload": <envelope>}``; the envelope is the payload:

    {
      "captured_at": "<ISO8601 UTC>|null",  # device sample time, ADVISORY (the Stack's receive
                                            #   time `last_heartbeat_at` is the authoritative clock)
      "onroad": false,                      # bool — cross-cutting state, no unit suffix
      "subsystems": {
        "thermal":  {"status", "max_c", "cpu_c", "gpu_c", "memory_c", "ambient_c"},
        "storage":  {"used_pct", "total_bytes", "used_bytes", "free_bytes"},
        "gps":      {"status"},
        "driving":  {"speed_ms", "heading_deg", "latitude", "longitude", "accuracy_m"},
        "panda":    {"status"},
        "power":    {"uptime_s"},
        "platform": {"name", "device_type"},
        "software": {"version", "branch", "update_channel", "update_state", "target_version"},
        "models":   {"active_ref", "installed_refs", "available"},
      }
    }

The ``driving`` subsystem carries LIVE motion while onroad (every field nullable — GPS has a
~20-30s warmup, so position is null early; ``heading_deg`` is null below a low speed where it's
noise; all fields are null off-device/offroad). ``latitude``/``longitude`` are bare coordinates
(identifier-like, no suffix). Position is privacy-sensitive — the Stack must own-scope its realtime
fan-out before broadcasting it (see the realtime manager).

UNIT CONVENTION — every dimensioned number carries exactly one suffix; this is the contract, enforced
by convention (single-author project), not a runtime registry:

    _c      degrees Celsius          _pct    percent (0-100)
    _bytes  bytes                    _s      seconds
    _m      meters                   _count  a count
    _ms     meters/second            _deg    degrees

Identifier/label strings (``name``, ``version``, ``branch``, ``*_ref``, ``device_type``) carry no
suffix. Booleans (``onroad``) carry no suffix.

ENUMS — closed sets; a raw on-device value outside the set normalizes to ``None`` (never an invented
string). A subsystem that's absent means the build/device lacks it; a present field that's ``None``
means the sensor reported nothing this sample.

There is no body version field: the agent and Stack are deployed and rebuilt together, so the shape
just changes in lockstep. The handshake ``protocol_version`` in settings-sync capabilities is
unrelated and unchanged.
"""

from __future__ import annotations

# Closed enum sets (value -> canonical). Anything else normalizes to None via `norm_enum`.
THERMAL_STATUSES = ("green", "yellow", "red")
GPS_STATUSES = ("has_fix", "searching", "no_signal", "error")
PANDA_STATUSES = ("connected", "available", "disconnected")
UPDATE_STATES = ("idle", "downloading", "installing", "done", "failed")
# PRNDL gear from carState.gearShifter (openpilot enum names; verified on the RAM). "sport"/"low"/
# "manumatic*"/"brake"/"eco" are other valid openpilot values kept so they pass through, not None.
GEAR_STATES = ("park", "drive", "reverse", "neutral", "sport", "low", "brake", "eco",
               "manumatic", "unknown")


def norm_enum(value, allowed: tuple[str, ...]) -> str | None:
    """Return value if it's in the closed set, else None (never an invented string)."""
    return value if value in allowed else None
