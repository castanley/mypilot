"""A deliberately thorough simulated comma device.

It drives the entire MyPilot UI/backend during M1/M2: realistic status telemetry, an
onroad/offroad state, and command handling (currently the offroad-only reboot). New simulated
capabilities (settings, models, routes, logs) are added here in later milestones.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import time
from datetime import datetime, timedelta, timezone

from .base import DeviceBackend

PLATFORMS = [
    "HYUNDAI IONIQ 5 2022",
    "TOYOTA RAV4 2021",
    "HONDA CIVIC 2022",
    "SUBARU OUTBACK 2020",
]

# (start, end, distance_km, duration_s) for the sample drives the device backfills on first run.
SAMPLE_TRIPS = [
    ("Home", "Grocery store", 7.8, 612),
    ("Home", "Office", 21.3, 1685),
    ("Office", "Home", 22.1, 1740),
]


class SimulatedDevice(DeviceBackend):
    def __init__(
        self,
        hardware_id: str,
        hostname: str,
        *,
        onroad: bool = False,
        cycle: bool = False,
        software_version: str = "0.9.8-mypilot",
        branch: str = "mypilot-release",
        platform: str | None = None,
    ) -> None:
        self.hardware_id = hardware_id
        self.hostname = hostname
        self._onroad = onroad
        self._cycle = cycle
        self.software_version = software_version
        self.branch = branch
        self.platform = platform or random.choice(PLATFORMS)
        self._storage_pct = random.uniform(30.0, 55.0)
        self._cpu_temp = random.uniform(45.0, 60.0)
        self._speed_ms = 0.0  # simulated live vehicle speed (random-walk while onroad)
        self._heading_deg = random.uniform(0.0, 360.0)  # slowly turns while onroad
        self._lat = 37.7749 + random.uniform(-0.05, 0.05)  # SF-ish start; walks while driving
        self._lon = -122.4194 + random.uniform(-0.05, 0.05)
        self._started = time.time()
        self._rebooting = False

        # Device capability vector (gates which settings the panel shows).
        self.capabilities = {
            "protocol_version": 1,
            "has_longitudinal_control": False,
            "has_icbm": False,
            "icbm_available": True,
            "torque_allowed": True,
            "steer_control_type": "torque",
            "brand": "honda",
            "pcm_cruise": True,
            "alpha_long_available": False,
            "enable_bsm": True,
            "is_release": False,
            "has_stop_and_go": False,
            "stock_longitudinal": False,
            "device_type": "tici",
        }
        # Current settings values (unreported keys fall back to catalog defaults server-side).
        self.settings: dict = {}

        # M5/M7 state: active driving model, installed models, software/update channel.
        self.active_model = "default-stock"
        self.installed_models = ["default-stock"]
        self.update_channel = "release"
        self.update_state = "idle"
        self.target_version: str | None = None
        self._http = None  # signed HTTP client injected by the runner (model downloads)

    def attach_http(self, client) -> None:
        self._http = client

    def settings_sync_payload(self) -> dict:
        return {"capabilities": self.capabilities, "values": dict(self.settings)}

    def apply_setting(self, key: str, value) -> tuple[bool, str]:
        # The Stack already enforces offroad/danger/capability gating; the simulated device
        # simply records the value. (A real agent would also honor on-device constraints.)
        self.settings[key] = value
        print(f"[sim] setting applied: {key} = {value!r}")
        return True, "applied"

    @property
    def onroad(self) -> bool:
        return self._onroad

    def set_onroad(self, value: bool) -> None:
        self._onroad = value

    def _thermal(self) -> str:
        if self._cpu_temp > 75:
            return "red"
        if self._cpu_temp > 65:
            return "yellow"
        return "green"

    def status(self) -> dict:
        # Gentle random walk so the dashboard looks alive. Emits the telemetry envelope (same
        # contract as the real device — see mypilot_protocol.telemetry).
        self._storage_pct = min(95.0, max(5.0, self._storage_pct + random.uniform(-0.3, 0.5)))
        target = 70.0 if self._onroad else 52.0
        self._cpu_temp += (target - self._cpu_temp) * 0.1 + random.uniform(-1.5, 1.5)
        cpu = round(self._cpu_temp, 1)
        # Simulated live speed: random-walk toward ~25 m/s (~56 mph) while onroad, coast to 0 when parked.
        if self._onroad:
            self._speed_ms = min(33.0, max(0.0, self._speed_ms + random.uniform(-2.0, 2.5)))
            self._heading_deg = (self._heading_deg + random.uniform(-8.0, 8.0)) % 360.0
        else:
            self._speed_ms = 0.0
        speed_ms = round(self._speed_ms, 2) if self._onroad else None
        # Heading only when actually moving (mirror the real backend's low-speed null).
        heading_deg = round(self._heading_deg, 1) if (self._onroad and self._speed_ms >= 1.5) else None
        # Walk the position along the heading at the current speed (1 status ~ a few sim-seconds), and
        # only expose it while moving — mirrors the real backend's parked-jitter guard.
        lat = lon = accuracy_m = None
        if self._onroad and self._speed_ms >= 0.5:
            import math
            dist_m = self._speed_ms * 3.0  # ~3s between samples
            self._lat += (dist_m * math.cos(math.radians(self._heading_deg))) / 111_320.0
            self._lon += (dist_m * math.sin(math.radians(self._heading_deg))) / (
                111_320.0 * math.cos(math.radians(self._lat)))
            lat, lon, accuracy_m = round(self._lat, 6), round(self._lon, 6), round(random.uniform(2.0, 6.0), 1)
        used_pct = round(self._storage_pct, 1)
        total = 256 * 10**9
        used = int(total * used_pct / 100.0)
        return {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "onroad": self._onroad,
            "subsystems": {
                "thermal": {"status": self._thermal(), "max_c": cpu, "cpu_c": cpu,
                            "gpu_c": round(cpu - 3, 1), "memory_c": round(cpu - 2, 1),
                            "ambient_c": round(cpu - 10, 1)},
                "storage": {"used_pct": used_pct, "total_bytes": total,
                            "used_bytes": used, "free_bytes": total - used},
                "gps": {"status": "has_fix" if self._onroad else "searching"},
                "driving": {"speed_ms": speed_ms, "heading_deg": heading_deg,
                            "latitude": lat, "longitude": lon, "accuracy_m": accuracy_m,
                            "gear": "drive" if self._onroad else "park"},
                "panda": {"status": "connected" if self._onroad else "available"},
                "power": {"uptime_s": int(time.time() - self._started)},
                "platform": {"name": self.platform, "device_type": "sim"},
                "software": {"version": self.software_version, "branch": self.branch,
                             "update_channel": self.update_channel,
                             "update_state": self.update_state, "target_version": self.target_version},
                "models": {"active_ref": self.active_model,
                           "installed_refs": list(self.installed_models), "available": []},
            },
        }

    async def execute(self, name: str, args: dict) -> tuple[bool, str]:
        if name == "reboot":
            # Defense in depth: the Stack gates this offroad, and so do we.
            if self._onroad:
                return False, "refused: device is onroad"
            self._rebooting = True
            print("[sim] reboot command received — simulating reboot...")
            await asyncio.sleep(2.0)
            self._started = time.time()
            self._rebooting = False
            print("[sim] reboot complete.")
            return True, "rebooted"

        if name == "switch_model":
            # Safety: model switching is offroad-only (the Stack gates this too).
            if self._onroad:
                return False, "refused: device is onroad"
            key = args.get("model_key")
            checksum = args.get("checksum")
            if not key:
                return False, "no model_key"
            if self._http is None:
                return False, "no download channel"
            try:
                data = await self._http.download_model(key)
            except Exception as exc:  # noqa: BLE001
                return False, f"download failed: {exc}"
            actual = hashlib.sha256(data).hexdigest()
            if checksum and actual != checksum:
                print(f"[sim] model {key} checksum mismatch ({actual[:8]} != {checksum[:8]})")
                return False, "checksum verification failed"
            self.active_model = key
            if key not in self.installed_models:
                self.installed_models.append(key)
            print(f"[sim] model switched -> {key} ({len(data)} bytes, sha256 verified)")
            return True, f"model {key} active"

        if name == "restore_settings":
            if self._onroad:
                return False, "refused: device is onroad"
            applied = args.get("settings") or {}
            for k, v in applied.items():
                self.settings[k] = v
            print(f"[sim] restored {len(applied)} settings from backup")
            return True, f"restored {len(applied)} settings"

        if name == "software_update":
            if self._onroad:
                return False, "refused: device is onroad"
            version = args.get("version")
            channel = args.get("channel")
            if not version:
                return False, "no version"
            self.update_state = "downloading"
            self.target_version = version
            await asyncio.sleep(1.0)
            self.update_state = "installing"
            await asyncio.sleep(1.0)
            self.software_version = version
            if channel:
                self.update_channel = channel
            self.update_state = "idle"
            self.target_version = None
            print(f"[sim] software updated -> {version} ({channel})")
            return True, f"updated to {version}"

        return False, f"unknown command: {name}"

    def generate_artifacts(self) -> tuple[list[dict], list[dict]]:
        """Build a few realistic recorded drives + device logs with real (small) byte payloads.

        These stand in for openpilot's segment logs: each file carries a recognizable header and
        some entropy so the Stack stores — and the UI downloads — genuine bytes (no facade).
        """
        now = datetime.now(timezone.utc)
        routes: list[dict] = []
        for i, (start_loc, end_loc, dist_km, dur_s) in enumerate(SAMPLE_TRIPS):
            started = now - timedelta(hours=(len(SAMPLE_TRIPS) - i) * 5)
            ended = started + timedelta(seconds=dur_s)
            segments = max(1, min(3, dur_s // 60))
            files = []
            for seg in range(segments):
                header = f"MYPILOT_QLOG {self.hardware_id} seg={seg} v={self.software_version}\n"
                files.append(
                    {
                        "segment_index": seg,
                        "name": "qlog.zst",
                        "kind": "qlog",
                        "data": header.encode("utf-8") + os.urandom(1536),
                    }
                )
            routes.append(
                {
                    "name": started.strftime("%Y-%m-%d--%H-%M-%S"),
                    "alias": f"{start_loc} → {end_loc}",
                    "started_at": started.isoformat(),
                    "ended_at": ended.isoformat(),
                    "duration_s": int(dur_s),
                    "distance_m": round(dist_km * 1000, 1),
                    "segment_count": int(segments),
                    "start_location": start_loc,
                    "end_location": end_loc,
                    "files": files,
                }
            )

        boot_txt = (
            f"[boot] MyPilot agent {self.software_version} on {self.platform}\n"
            f"[boot] hardware_id={self.hardware_id}\n"
            "[boot] panda: connected\n[boot] thermald: ok\n[boot] manager: started all processes\n"
        )
        crash_txt = (
            "Traceback (most recent call last):\n"
            '  File "selfdrive/controls/controlsd.py", line 412, in step\n'
            "    self.update(sm)\n"
            "RuntimeError: simulated non-fatal worker exception (sample crash log)\n"
        )
        logs = [
            {"kind": "system", "name": "boot.log", "route_name": None, "data": boot_txt.encode("utf-8")},
            {
                "kind": "crash",
                "name": f"crash_{now.strftime('%Y-%m-%d')}.txt",
                "route_name": routes[-1]["name"] if routes else None,
                "data": crash_txt.encode("utf-8"),
            },
        ]
        return routes, logs

    async def run_state_cycler(self) -> None:
        """Optionally toggle onroad/offroad every ~30s to demonstrate live state changes."""
        if not self._cycle:
            return
        while True:
            await asyncio.sleep(30)
            self._onroad = not self._onroad
            print(f"[sim] state -> {'onroad' if self._onroad else 'offroad'}")
