"""Real comma-device backend (openpilot/SunnyPilot).

Implements the :class:`DeviceBackend` contract against on-device APIs (Params, cereal, hardware,
SunnyPilot's Model Manager + updater). openpilot imports are **lazy** so the package still imports
on a dev machine; on a comma device the methods do real work over the network — no SSH.

All driving-affecting actions are **offroad-only** (defense in depth on top of the Stack's gate),
and nothing here touches controlsd / pandad / driver monitoring / torque or panda safety.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone

from mypilot_protocol.telemetry import (
    GEAR_STATES,
    GPS_STATUSES,
    THERMAL_STATUSES,
    UPDATE_STATES,
    norm_enum,
)

from .base import DeviceBackend

PAIRING_ALERT = "Offroad_MyPilotPairing"
# Prebuilt-safe pairing surface: the on-screen settings panel (MyPilot Link → Pair) reads this file
# to render the QR + PIN. We can't use a Params key for this — on a prebuilt branch params_pyx.so is
# precompiled, so writing an undeclared key (Offroad_MyPilotPairing) raises UnknownKeyName. A plain
# file under the agent's data dir works on every branch with no recompile.
PAIRING_FILE = "/data/mypilot/pairing.json"
# Web pair page; the QR encodes this with the one-time code so a phone scan prefills the PIN.
PAIR_URL_BASE = "https://mypilot.me/devices/pair"


def _try_params():
    try:
        from openpilot.common.params import Params  # type: ignore

        return Params()
    except Exception:  # noqa: BLE001 - not on-device / openpilot not importable
        return None


# GPS publishes under different service names depending on the GNSS source: comma 3X/external pucks
# use gpsLocationExternal, the comma 4 / qcom modem uses gpsLocation. Subscribe to whichever the
# build registers (SubMaster raises on an unknown service name) so we read the one that's live.
_GPS_SERVICES = ("gpsLocationExternal", "gpsLocation")
# carState carries vehicle speed (vEgo, m/s) — the authoritative live-speed source while onroad.
_CARSTATE_SERVICE = "carState"
# GPS bearing is unreliable at very low speed (a near-stationary fix jitters its heading), so null
# heading below this — matches the parked-jitter philosophy used for the route track.
_HEADING_MIN_SPEED_MS = 1.5


class _Sampler:
    """Lightweight, low-rate telemetry reader. MyPilot only samples once per heartbeat (0.1-0.5Hz),
    so it must NOT run a SubMaster that pumps the full 10-100Hz streams — that buffered msgq and could
    backpressure the publisher (suspected cause of the driving-stack CPU saturation / commIssue alerts).

    Instead each service gets ONE conflate=True sub_sock (msgq keeps only the latest message, dropping
    the backlog), and `latest(svc)` does a single non-blocking receive returning just the newest frame
    — O(1), no draining, no backlog. The last good message is cached so a tick with nothing new still
    returns the most recent value."""

    def __init__(self) -> None:
        self._socks: dict = {}
        self._last: dict = {}
        try:
            from cereal import messaging  # type: ignore
            from cereal.services import SERVICE_LIST  # type: ignore
        except Exception:  # noqa: BLE001 - not on-device
            return
        self._messaging = messaging
        # Subscribe ONLY to services status() actually reads — every extra conflate sock still has
        # msgq copy a frame into its ring on each publish, so an unread sub is pure waste on the
        # shared cores. (panda status is a stub derived from onroad; no pandaStates sub needed.)
        want = ["deviceState", _CARSTATE_SERVICE]
        want += list(_GPS_SERVICES)
        for svc in want:
            if svc in SERVICE_LIST:
                try:
                    # conflate=True -> only the newest msg is ever queued; timeout=0 -> non-blocking.
                    self._socks[svc] = messaging.sub_sock(svc, conflate=True, timeout=0)
                except Exception:  # noqa: BLE001
                    pass

    def latest(self, svc: str):
        """The most recent message for svc (cached), or None if never received. Cheap: one non-blocking
        recv that returns at most the single latest (conflated) frame."""
        sock = self._socks.get(svc)
        if sock is None:
            return None
        try:
            # ONE non-blocking receive — never a drain loop. conflate=True means msgq only ever
            # holds the newest frame, so a single receive() gets it. A `while` here would, after
            # any event-loop stall, decode the whole accumulated backlog in a tight burst on the
            # shared cores — the positive-feedback amplifier we must avoid (commIssue). Cap at 1.
            raw = sock.receive(non_blocking=True)
            if raw is not None:
                self._last[svc] = self._messaging.log_from_bytes(raw)
        except Exception as exc:  # noqa: BLE001
            # Don't mask a decode/socket storm silently — a single throttled line aids triage.
            print(f"[mypilot] sampler latest({svc}) error: {exc}", flush=True)
        msg = self._last.get(svc)
        if msg is None:
            return None
        try:
            return getattr(msg, msg.which())
        except Exception:  # noqa: BLE001
            return None


def _try_submaster():
    try:
        return _Sampler()
    except Exception:  # noqa: BLE001
        return None


def _device_type() -> str | None:
    try:
        from openpilot.system.hardware import HARDWARE  # type: ignore

        return HARDWARE.get_device_type()
    except Exception:  # noqa: BLE001
        return None


class RealDevice(DeviceBackend):
    def __init__(self, hardware_id: str, hostname: str) -> None:
        self.hardware_id = hardware_id
        self.hostname = hostname
        self._params = _try_params()
        self._sm = _try_submaster()
        self._http = None
        self._started = time.time()
        self._device_type = _device_type()
        self.update_channel = self._param_str("UpdaterTargetBranch") or self._param_str("GitBranch")
        # Per-tick read cache. status() runs on the event loop every heartbeat; without this it would
        # do ~9-11 Params IPC round-trips + a statvfs + 2 JSON parses + a capnp decode EVERY tick,
        # most for values that change rarely or never. Caching slow/static reads keeps the per-tick
        # cost ~constant so the agent never spikes the shared cores (commIssue). Values stay current
        # within their TTL; immutable ones (platform/version/branch) are read once. NB: `onroad` is
        # deliberately NOT cached — command guards depend on a fresh read for safety.
        self._cache: dict[str, tuple[float, object]] = {}

    def _cached(self, key: str, ttl: float, producer):
        """Return producer()'s value, recomputing only when older than ttl seconds. ttl<=0 means
        cache-once-forever (for values that can't change during a session, e.g. the car platform)."""
        now = time.time()
        hit = self._cache.get(key)
        if hit is not None and (ttl <= 0 or (now - hit[0]) < ttl):
            return hit[1]
        val = producer()
        # Cache-once entries (ttl<=0) only stick once they resolve to something real, so a transient
        # None (e.g. platform before the car is seen) is retried next tick rather than frozen.
        if ttl > 0 or val is not None:
            self._cache[key] = (now, val)
        return val

    def _invalidate(self, *keys: str) -> None:
        for k in keys:
            self._cache.pop(k, None)

    # --- wiring -------------------------------------------------------------------------------
    def attach_http(self, client) -> None:
        self._http = client

    def _param_str(self, key: str) -> str | None:
        if self._params is None:
            return None
        try:
            # NB: the on-device (prebuilt) Params.get has signature get(key, block, return_default)
            # with NO encoding kwarg — passing encoding= raises TypeError and would silently break
            # all status/version reporting. It already returns a decoded str for STRING keys.
            val = self._params.get(key)
            if isinstance(val, bytes):
                val = val.decode("utf8", "replace")
            return val or None
        except Exception:  # noqa: BLE001
            return None

    def _read_json_param(self, key: str):
        if self._params is None:
            return None
        try:
            val = self._params.get(key)
        except Exception:  # noqa: BLE001
            return None
        if val is None:
            return None
        if isinstance(val, (bytes, str)):
            try:
                return json.loads(val)
            except Exception:  # noqa: BLE001
                return None
        return val  # fork's Params.get may already decode JSON to dict/list

    def _platform(self) -> str | None:
        """The detected car, from the CarParams capnp struct (carFingerprint, e.g.
        'CHRYSLER_RAM_HD'). CarName/CarModel are NOT params on a prebuilt branch (they raise
        UnknownKeyName), so the old read always came back blank. CarParams is written once the car
        is recognized; CarParamsPersistent survives across the offroad transition so the dashboard
        still shows the platform while parked. Returns None until a car has been seen at least once."""
        if self._params is None:
            return None
        try:
            from cereal import car, messaging  # type: ignore
        except Exception:  # noqa: BLE001 - not on-device
            return None
        for key in ("CarParams", "CarParamsPersistent", "CarParamsCache"):
            try:
                raw = self._params.get(key)
            except Exception:  # noqa: BLE001
                continue
            if not raw:
                continue
            try:
                cp = messaging.log_from_bytes(raw, car.CarParams)
                fp = cp.carFingerprint or None
                # carFingerprint is an upper-snake platform code; make it a touch friendlier.
                return fp.replace("_", " ").title() if fp else None
            except Exception:  # noqa: BLE001 - malformed/partial struct
                continue
        return None

    @staticmethod
    def _bundles(cache) -> list:
        if isinstance(cache, list):
            return [b for b in cache if isinstance(b, dict)]
        if isinstance(cache, dict):
            if isinstance(cache.get("bundles"), list):
                return [b for b in cache["bundles"] if isinstance(b, dict)]
            vals = [v for v in cache.values() if isinstance(v, dict)]
            if vals:
                return vals
        return []

    @staticmethod
    def _bundle_name(b: dict) -> str | None:
        # SunnyPilot's Model Manager catalog uses snake_case: display_name ("LAv2 (January 24,
        # 2024)") + short_name ("LAV2"). Older/other forks may use camelCase displayName — accept
        # both. The ref is a 40-char content hash; only use it as a last-resort label.
        return (
            b.get("display_name")
            or b.get("displayName")
            or b.get("short_name")
            or b.get("ref")
        )

    def _active_model_ref(self) -> str | None:
        active = self._read_json_param("ModelManager_ActiveBundle")
        if isinstance(active, dict):
            # key must stay the stable ref (the Stack round-trips it back as model_key); the label
            # is resolved from it in _available_models / the Stack view.
            return active.get("ref") or self._bundle_name(active)
        return None

    def _available_models(self) -> list[dict]:
        bundles = self._bundles(self._read_json_param("ModelManager_ModelsCache"))
        out = []
        for b in bundles:
            # key = the stable identifier the switch flow matches on (ref preferred, else index).
            key = b.get("ref") or (str(b["index"]) if "index" in b else None)
            if not key:
                continue
            out.append(
                {
                    "key": key,
                    "name": self._bundle_name(b) or key,
                    "generation": str(b["generation"]) if b.get("generation") is not None else None,
                    "runner": b.get("runner"),
                }
            )
        return out

    # --- state --------------------------------------------------------------------------------
    @property
    def onroad(self) -> bool:
        if self._params is not None:
            try:
                return bool(self._params.get_bool("IsOnroad"))
            except Exception:  # noqa: BLE001
                pass
        if self._sm is not None:
            try:
                # Fallback only (when the IsOnroad param is unavailable): latest deviceState.started.
                ds = self._sm.latest("deviceState")
                if ds is not None:
                    return bool(ds.started)
            except Exception:  # noqa: BLE001
                pass
        return False

    @staticmethod
    def _thermal_color(thermal_status) -> str | None:
        # deviceState.thermalStatus is a capnp enum (ok/green/yellow/red), NOT an int — int() on it
        # raises. Map by the enum's name; ok+green are both "fine", yellow=warn, red/danger=hot, then
        # normalize through the protocol's closed set (unknown -> None, never an invented string).
        name = str(thermal_status).rsplit(".", 1)[-1].lower()
        color = {"ok": "green", "green": "green", "yellow": "yellow", "red": "red", "danger": "red"}.get(name)
        return norm_enum(color, THERMAL_STATUSES)

    @staticmethod
    def _storage_bytes() -> dict | None:
        """Absolute /data storage (total/used/free bytes). deviceState only carries a free PERCENT,
        so we statvfs the data partition for real sizes. Used by the dashboard to show e.g.
        "6.1 / 94.5 GB" next to the percentage."""
        try:
            st = os.statvfs("/data")
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            return {"total_bytes": total, "free_bytes": free, "used_bytes": total - free}
        except Exception:  # noqa: BLE001 - not on-device / path missing
            return None

    @staticmethod
    def _max_list(v) -> float | None:
        """deviceState temps are sometimes a scalar, sometimes a per-core capnp list. Reduce to the
        hottest reading; None if empty/unavailable. NB: capnp's list reader is NOT __iter__-able via
        hasattr but IS indexable/len()-able, so detect a sequence via len()+list() rather than
        __iter__ (that bug made cpu/gpu temps read None)."""
        try:
            try:
                vals = [float(x) for x in list(v)]  # works for capnp lists AND python lists
            except TypeError:
                vals = [float(v)]  # a bare scalar
            vals = [x for x in vals if x > -100]  # drop sentinel/unpopulated (-40 etc.)
            return round(max(vals), 1) if vals else None
        except Exception:  # noqa: BLE001
            return None

    def status(self) -> dict:
        """Build the telemetry envelope. See mypilot_protocol.telemetry for the contract: envelope
        {captured_at, onroad, subsystems{...}}, units in keys, enums normalized to a closed set.
        Single source of truth per metric — no duplication."""
        onroad = self.onroad

        thermal = {"status": None, "max_c": None, "cpu_c": None, "gpu_c": None,
                   "memory_c": None, "ambient_c": None}
        gps_status = None
        speed_ms = None
        heading_deg = None
        latitude = longitude = accuracy_m = None
        gear = None
        if self._sm is not None:
            try:
                # Read the latest conflated frame per service — O(1), non-blocking, no stream draining
                # (see _Sampler). The agent samples at heartbeat rate, never pumps the 10-100Hz streams.
                ds = self._sm.latest("deviceState")
                if ds is not None:
                    thermal["status"] = self._thermal_color(ds.thermalStatus)
                    thermal["cpu_c"] = self._max_list(ds.cpuTempC)
                    thermal["gpu_c"] = self._max_list(ds.gpuTempC)
                    thermal["memory_c"] = self._max_list(ds.memoryTempC)
                    thermal["ambient_c"] = self._max_list(ds.bottomSocTempC)
                    try:
                        thermal["max_c"] = round(float(ds.maxTempC), 1)
                    except Exception:  # noqa: BLE001
                        cands = [v for k, v in thermal.items() if k.endswith("_c") and v is not None]
                        thermal["max_c"] = max(cands) if cands else None
                # GPS daemon typically only runs onroad; report no_signal offroad rather than blank.
                gps_status = "no_signal"
                gps_speed = None
                gps_bearing = None
                gps_lat = gps_lon = gps_acc = None
                for svc in _GPS_SERVICES:
                    g = self._sm.latest(svc)
                    if g is not None:
                        has_fix = bool(getattr(g, "hasFix", False))
                        gps_status = "has_fix" if has_fix else "searching"
                        gps_speed = getattr(g, "speed", None)  # m/s, Doppler-derived
                        if has_fix:
                            # comma-4 gpsLocation(External) names this `bearingDeg`; older/3X GNSS used
                            # `bearing`. Read bearingDeg first, fall back to bearing — else heading is
                            # always null (the bug where the live arrow stuck pointing north).
                            gps_bearing = getattr(g, "bearingDeg", None)
                            if gps_bearing is None:
                                gps_bearing = getattr(g, "bearing", None)  # degrees, 0=N
                            gps_lat = getattr(g, "latitude", None)
                            gps_lon = getattr(g, "longitude", None)
                            # accuracy field also differs: horizontalAccuracy on comma-4, accuracy on 3X.
                            gps_acc = getattr(g, "horizontalAccuracy", None)
                            if gps_acc is None:
                                gps_acc = getattr(g, "accuracy", None)   # horizontal, meters
                        break
                # Live vehicle speed: carState.vEgo is the authoritative source; fall back to the GPS
                # Doppler speed when carState isn't published (e.g. some builds / before the car is up).
                cs = self._sm.latest(_CARSTATE_SERVICE)
                if cs is not None:
                    speed_ms = float(cs.vEgo)
                    # PRNDL gear from the car. The enum stringifies to park/reverse/neutral/drive/...
                    # (verified on the RAM); normalize to that closed set, else None.
                    gear = norm_enum(str(cs.gearShifter), GEAR_STATES)
                elif gps_speed is not None:
                    speed_ms = float(gps_speed)
                if speed_ms is not None:
                    speed_ms = round(max(0.0, speed_ms), 2)
                # Heading from GPS bearing — only trustworthy when actually moving (see threshold).
                if gps_bearing is not None and speed_ms is not None and speed_ms >= _HEADING_MIN_SPEED_MS:
                    heading_deg = round(float(gps_bearing) % 360.0, 1)
                # Live position — report it on ANY valid fix (parked or moving) so the map always shows
                # where the car IS, not just while driving. (The earlier speed-gate hid a parked car's
                # location entirely.) Parked GPS jitter is handled where it matters — the accumulating
                # TRAIL has its own min-move filter server-side (update_live_track), so a stationary
                # car won't draw a scribble even though we report its current point here.
                if gps_lat is not None and gps_lon is not None:
                    lat, lon = float(gps_lat), float(gps_lon)
                    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and not (lat == 0.0 and lon == 0.0):
                        latitude, longitude = round(lat, 6), round(lon, 6)
                        if gps_acc is not None:
                            accuracy_m = round(float(gps_acc), 1)
            except Exception:  # noqa: BLE001
                pass

        # Storage moves slowly; statvfs every 4s is wasted syscalls — refresh ~every 20s.
        storage = self._cached("storage", 20.0, lambda: self._storage_bytes() or {})
        used_pct = None
        if storage.get("total_bytes"):
            used_pct = round(100.0 * storage["used_bytes"] / storage["total_bytes"], 1)

        # Active model only changes on an explicit switch (we invalidate then); cache ~31s otherwise.
        # TTLs are deliberately co-prime-ish (storage 20 / updater 15 / active 31 / available 37) so
        # the cache misses don't align onto one heavier tick — keeps per-tick IPC flat, no micro-spike.
        active = self._cached("active_model", 31.0, self._active_model_ref)

        return {
            "captured_at": self._now_iso(),
            "onroad": onroad,
            "subsystems": {
                "thermal": thermal,
                "storage": {
                    "used_pct": used_pct,
                    "total_bytes": storage.get("total_bytes"),
                    "used_bytes": storage.get("used_bytes"),
                    "free_bytes": storage.get("free_bytes"),
                },
                "gps": {"status": norm_enum(gps_status, GPS_STATUSES)},
                # Live motion telemetry. All fields null off-device / not moving / no fix. Position
                # streams only behind owner-scoped realtime fan-out (privacy). `gear` = PRNDL.
                "driving": {"speed_ms": speed_ms, "heading_deg": heading_deg,
                            "latitude": latitude, "longitude": longitude, "accuracy_m": accuracy_m,
                            "gear": gear},
                # panda is a stub derived from onroad (no real panda-state source yet).
                "panda": {"status": "connected" if onroad else "available"},
                "power": {"uptime_s": int(time.time() - self._started)},
                # platform (carFingerprint) is immutable for the session -> cache once it resolves.
                "platform": {"name": self._cached("platform", 0, self._platform),
                             "device_type": self._device_type},
                "software": {
                    # Version + branch are boot-constant -> read once. UpdaterState changes rarely.
                    "version": self._cached("version", 0, lambda: self._param_str("Version")),
                    "branch": self._cached("branch", 0, lambda: self._param_str("GitBranch")),
                    "update_channel": self.update_channel,
                    "update_state": norm_enum(
                        self._cached("updater_state", 15.0, lambda: self._param_str("UpdaterState")),
                        UPDATE_STATES) or "idle",
                    "target_version": None,
                },
                "models": {
                    "active_ref": active,
                    "installed_refs": [active] if active else [],
                    "available": self._cached("available_models", 37.0, self._available_models),
                },
            },
        }

    @staticmethod
    def _now_iso() -> str | None:
        # Advisory device sample time. The Stack's receive-time (last_heartbeat_at) is authoritative;
        # the device clock can be skewed pre-NTP, so this is informational only.
        try:
            return datetime.now(timezone.utc).isoformat()
        except Exception:  # noqa: BLE001
            return None

    # --- pairing (on-screen, no SSH) ----------------------------------------------------------
    def show_pairing_code(self, code: str, expires_at: str | None = None) -> None:
        # Primary surface (works on prebuilt): write the code to a file the MyPilot Link → Pair
        # screen reads to render the QR + PIN.
        try:
            os.makedirs(os.path.dirname(PAIRING_FILE), exist_ok=True)
            payload = {
                "code": code,
                "url": f"{PAIR_URL_BASE}?code={code}",
                "expires_at": expires_at,
            }
            tmp = PAIRING_FILE + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(payload, fh)
            os.replace(tmp, PAIRING_FILE)  # atomic so the UI never reads a half-written file
        except Exception as exc:  # noqa: BLE001 - display is best-effort, never fatal
            print(f"[mypilot] could not write pairing file: {exc}", flush=True)
        # Secondary surface (only works if the param is declared, e.g. a recompiled build): the
        # home-screen offroad alert. Best-effort; silently a no-op on a stock prebuilt branch.
        try:
            from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert  # type: ignore

            set_offroad_alert(PAIRING_ALERT, True, extra_text=code)
        except Exception:  # noqa: BLE001
            pass

    def clear_pairing_code(self) -> None:
        try:
            if os.path.exists(PAIRING_FILE):
                os.remove(PAIRING_FILE)
        except Exception:  # noqa: BLE001
            pass
        try:
            from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert  # type: ignore

            set_offroad_alert(PAIRING_ALERT, False)
        except Exception:  # noqa: BLE001
            pass

    # --- settings -----------------------------------------------------------------------------
    def settings_sync_payload(self) -> dict:
        caps: dict = {"protocol_version": 1}
        if self._device_type:
            caps["device_type"] = self._device_type
        # Brand from the detected platform (e.g. "Chrysler Ram Hd" -> "chrysler"); CarName isn't a
        # param on a prebuilt branch. None until a car has been seen.
        platform = self._platform()
        if platform:
            caps["brand"] = platform.split()[0].lower()
        return {"capabilities": caps, "values": {}}

    def apply_setting(self, key: str, value) -> tuple[bool, str]:
        if self.onroad:
            return False, "refused: device is onroad"
        if self._params is None:
            return False, "params unavailable"
        try:
            if isinstance(value, bool):
                self._params.put_bool(key, value)
            else:
                # Write the value's NATIVE type (int/float/str). The on-device Params are typed and
                # reject a type mismatch — e.g. an INT param like SpeedLimitMode raises TypeError on
                # put("0") but accepts put(0). The Stack already sends correctly-typed JSON, so pass
                # it straight through; only coerce a genuine string param.
                self._params.put(key, value)
            return True, "applied"
        except Exception as exc:  # noqa: BLE001
            return False, f"params write failed: {exc}"

    # --- commands -----------------------------------------------------------------------------
    async def execute(self, name: str, args: dict) -> tuple[bool, str]:
        if name == "reboot":
            if self.onroad:
                return False, "refused: device is onroad"
            try:
                from openpilot.system.hardware import HARDWARE  # type: ignore

                HARDWARE.reboot()
                return True, "rebooting"
            except Exception as exc:  # noqa: BLE001
                return False, f"reboot unavailable: {exc}"

        if name == "switch_model":
            return self._switch_model(args)

        if name == "software_update":
            return self._software_update(args)

        if name == "restore_settings":
            if self.onroad:
                return False, "refused: device is onroad"
            applied = sum(1 for k, v in (args.get("settings") or {}).items() if self.apply_setting(k, v)[0])
            return True, f"restored {applied} settings"

        return False, f"unknown command: {name}"

    def _switch_model(self, args: dict) -> tuple[bool, str]:
        # Real activation via SunnyPilot's Model Manager: set ModelManager_DownloadIndex; the
        # models_manager process downloads + SHA256-verifies the bundle, then sets the active
        # bundle. Reverting to stock removes ModelManager_ActiveBundle. Offroad-only.
        if self.onroad:
            return False, "refused: device is onroad"
        if self._params is None:
            return False, "params unavailable"
        ref = args.get("model_key")
        if not ref:
            return False, "no model_key"
        if str(ref).lower() in ("default", "stock", "default-stock"):
            try:
                self._params.remove("ModelManager_ActiveBundle")
            except Exception as exc:  # noqa: BLE001
                return False, f"failed: {exc}"
            self._invalidate("active_model", "available_models")  # reflect the change next heartbeat
            return True, "reverting to stock model"
        bundles = self._bundles(self._read_json_param("ModelManager_ModelsCache"))
        match = next(
            (
                b for b in bundles
                if ref in (
                    b.get("ref"), b.get("display_name"), b.get("displayName"),
                    b.get("short_name"), str(b.get("index")),
                )
            ),
            None,
        )
        if match is None or "index" not in match:
            return False, f"model '{ref}' not found in the on-device catalog"
        try:
            self._params.put("ModelManager_DownloadIndex", int(match["index"]))
        except Exception as exc:  # noqa: BLE001
            return False, f"failed to request model: {exc}"
        self._invalidate("active_model", "available_models")  # reflect the change next heartbeat
        return True, f"requested {self._bundle_name(match) or ref} — Model Manager will download + verify"

    def _software_update(self, args: dict) -> tuple[bool, str]:
        # Real update via SunnyPilot's updater: set the target branch and nudge `updated` to
        # fetch it. The device shows "Update available" and applies on the next reboot (offroad).
        if self.onroad:
            return False, "refused: device is onroad"
        if self._params is None:
            return False, "params unavailable"
        branch = args.get("branch") or self._branch_from_url(args.get("install_url"))
        if not branch:
            return False, "no target branch"
        try:
            self._params.put("UpdaterTargetBranch", branch)
        except Exception as exc:  # noqa: BLE001
            return False, f"failed to set target branch: {exc}"
        # Nudge the updater: SIGUSR1 = check, SIGHUP = download/fetch the target branch.
        for sig in ("-SIGUSR1", "-SIGHUP"):
            subprocess.run(["pkill", sig, "-f", "system.updated.updated"], check=False)
        self.update_channel = args.get("channel") or branch
        return True, f"update to {branch} started; device will fetch it and apply on next reboot"

    @staticmethod
    def _branch_from_url(url: str | None) -> str | None:
        if not url:
            return None
        return url.rstrip("/").split("/")[-1] or None

    # --- uploads ------------------------------------------------------------------------------
    def generate_artifacts(self) -> tuple[list, list]:
        # Route/log upload is OFF by default (privacy). Wire to the loggerd realdata root on opt-in.
        return [], []

    async def run_state_cycler(self) -> None:
        return None
