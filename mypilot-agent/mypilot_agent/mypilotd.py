"""On-device entrypoint: the process the openpilot manager launches for MyPilot.

Registered in `system/manager/process_config.py` as
``PythonProcess("mypilotd", "openpilot.sunnypilot.mypilot.mypilotd", always_run)``.

Reads `/data/mypilot/config.json` (created on first run with sensible defaults) for the Stack URL
and an enable flag, uses the comma DongleId as the MyPilot hardware id, and runs the real-device
agent. It is non-critical: a crash only stops MyPilot management (the manager restarts it); driving
is unaffected.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

DATA_DIR = "/data/mypilot"
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
FORK_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fork.json")
DEFAULT_STACK_URL = "https://mypilot.me"  # ultimate fallback; forks edit fork.json


def _ensure_vendored_on_path() -> None:
    """When vendored in the fork, the protocol + agent live next to this file."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)


def _fork_default_stack_url() -> str:
    """Build-time default from the fork knob (fork.json). One file for forks to change."""
    try:
        with open(FORK_JSON) as fh:
            return (json.load(fh) or {}).get("stack_url") or DEFAULT_STACK_URL
    except Exception:  # noqa: BLE001
        return DEFAULT_STACK_URL


def _load_config() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    default_url = _fork_default_stack_url()
    cfg = {"enabled": True, "stack_url": default_url}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as fh:
                cfg.update(json.load(fh) or {})
        except Exception:  # noqa: BLE001 - tolerate a malformed file; fall back to defaults
            pass
    else:
        try:
            with open(CONFIG_PATH, "w") as fh:
                json.dump(cfg, fh, indent=2)
        except Exception:  # noqa: BLE001
            pass
    # Precedence: env override > /data config > fork.json default.
    cfg["stack_url"] = os.environ.get("MYPILOT_STACK_URL", cfg.get("stack_url", default_url))
    return cfg


def _parse_cpu_list(s: str) -> set[int]:
    """Parse a Linux cpu-list string like "6-7" or "0,3-5" into a set of core ids."""
    out: set[int] = set()
    for part in s.strip().split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = part.split("-", 1)
                out.update(range(int(a), int(b) + 1))
            else:
                out.add(int(part))
        except ValueError:
            continue
    return out


def _lower_priority() -> None:
    """Make the agent a yield-to-everything sidecar so it can NEVER starve the driving stack.

    The live-telemetry features previously caused "Communication Issue Between Processes" /
    "TAKE CONTROL" alerts: not because the agent used much CPU (~4%), but because at default
    priority it injected scheduling jitter on the shared general cores (0-5) and delayed
    soft-realtime driving services (e.g. lateralManeuverPlan/alertDebug) past their publish
    deadline. Two cheap, privilege-free measures fix that for good while keeping every feature:

      1. SCHED_IDLE — the kernel only runs us on cycles no normal task wants, so any driving
         process always preempts us. Falls back to the lowest nice value if the policy is
         unavailable/disallowed. (Cores 0-5 sit ~50-80% busy, so a 0.25 Hz sidecar still gets
         ample idle cycles; it only steps aside during the 100% peaks — exactly when we must.)
      2. Affinity off the isolated driving cores — comma reserves cores 6-7 (isolcpus) for the
         hard-realtime stack; pin to the complement so we never even share a runqueue with them.

    All best-effort: any failure (dev machine, odd topology, missing privilege) is a silent no-op
    so the agent still runs. Lowering one's own scheduling priority needs no special privilege."""
    try:
        if hasattr(os, "SCHED_IDLE"):
            os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))  # type: ignore[attr-defined]
        else:
            raise OSError("SCHED_IDLE unavailable")
    except Exception:  # noqa: BLE001 - fall back to the universally-allowed nice bump
        try:
            os.nice(19)
        except Exception:  # noqa: BLE001
            pass
    try:
        isolated: set[int] = set()
        try:
            with open("/sys/devices/system/cpu/isolated") as fh:
                isolated = _parse_cpu_list(fh.read())
        except Exception:  # noqa: BLE001 - no isolation file / not on-device
            isolated = set()
        if isolated and hasattr(os, "sched_getaffinity"):
            allowed = set(os.sched_getaffinity(0))
            target = allowed - isolated
            if target and target != allowed:
                os.sched_setaffinity(0, target)
    except Exception:  # noqa: BLE001
        pass


def _dongle_id() -> str | None:
    try:
        from openpilot.common.params import Params  # type: ignore

        # The on-device (prebuilt) Params.get takes no encoding kwarg (get(key, block,
        # return_default)); passing encoding= raises TypeError, which would drop us to a random
        # hardware_id instead of the real DongleId. get() already returns a decoded str.
        val = Params().get("DongleId")
        if isinstance(val, bytes):
            val = val.decode("utf8", "replace")
        return val or None
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    _ensure_vendored_on_path()
    # Yield-to-everything scheduling FIRST, before any work — the driving stack must always win
    # the CPU. See _lower_priority(); this is what keeps live telemetry from causing commIssue.
    _lower_priority()

    cfg_file = _load_config()
    if not cfg_file.get("enabled", True):
        print("[mypilotd] disabled via /data/mypilot/config.json; exiting.")
        return

    from mypilot_agent.config import AgentConfig
    from mypilot_agent.runner import run

    cfg = AgentConfig(
        stack_url=cfg_file["stack_url"],
        data_dir=DATA_DIR,
        alias="comma device",
        onroad=False,
        cycle=False,
        hardware_id=_dongle_id(),
        reset=False,
        real=True,
    )
    print(f"[mypilotd] starting MyPilot agent -> {cfg.api_base}")
    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
