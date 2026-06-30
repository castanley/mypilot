#!/usr/bin/env python3
"""Apply the MyPilot overlay onto a fresh upstream openpilot tree (commaai/openpilot or FrogPilot).

These bases put the overlay at the repository root (``mypilot/``), so the launcher module is
``mypilot.mypilotd``. Run from the fork repo root after the overlay is in place. It:
  1. registers the MyPilot agent as a non-critical ``PythonProcess`` (mypilotd) whose launcher
     imports nothing at module load — so the manager's boot-time pre-import can never hang — and
  2. registers the on-screen pairing alert key.

Idempotent; touches no driving/safety code. Vanilla openpilot has no ``mapd_manager`` anchor, so we
insert the registration directly above the ``managed_processes = {...}`` construction line — NOT by
appending ``procs += [...]`` after end-of-file. The manager imports ``managed_processes`` (built
once from ``procs``); appending after that line would add the agent to ``procs`` but never to
``managed_processes``, so it would silently never launch.
"""

from __future__ import annotations

import json
import os
import re
import sys

PROC_PATH = "system/manager/process_config.py"
MODULE = "mypilot.mypilotd"

# Base tag for the version string (spelled out: "openpilot" / "frogpilot"). The root base serves both; we detect
# frogpilot by its marker so the tag is right. The version scheme on these experimental bases is not
# guaranteed (modern openpilot derives version from git tags, not a header), so the stamp is
# BEST-EFFORT here: stamp a #define-style version file if present, else skip — never break an
# experimental build over a cosmetic version.
VERSION_CANDIDATES = ("common/version.h", "selfdrive/common/version.h")


class AnchorError(RuntimeError):
    """An expected anchor was missing — fail the build rather than ship an agent that never runs."""

ALERTS_PATH = "selfdrive/selfdrived/alerts_offroad.json"
ALERT_KEY = "Offroad_MyPilotPairing"
ALERT_ENTRY = {
    "text": "MyPilot pairing code: %1\nEnter it in MyPilot Web \u2192 Devices \u2192 Add device.",
    "severity": 1,
}


def _register_process() -> None:
    with open(PROC_PATH) as fh:
        src = fh.read()
    if MODULE in src:
        print("[mypilot] mypilotd already registered")
        return
    block = (
        "procs += [\n"
        "  # MyPilot — self-hosted control plane agent. Non-critical sidecar; import-safe launcher,\n"
        "  # never in the driving path. restart_if_crash=True so a transient crash self-heals.\n"
        f'  PythonProcess("mypilotd", "{MODULE}", always_run, restart_if_crash=True),\n'
        "]\n\n"
    )
    marker = "managed_processes = {p.name: p for p in procs}"
    if src.count(marker) != 1:
        raise AnchorError(f"register_process: expected exactly 1 '{marker}' in {PROC_PATH}, found {src.count(marker)}")
    src = src.replace(marker, block + marker, 1)
    with open(PROC_PATH, "w") as fh:
        fh.write(src)
    print("[mypilot] registered mypilotd above managed_processes in", PROC_PATH)


def _register_pairing_alert() -> None:
    try:
        with open(ALERTS_PATH) as fh:
            alerts = json.load(fh)
    except FileNotFoundError:
        print("[mypilot] alerts file not found; skipping pairing alert")
        return
    if ALERT_KEY in alerts:
        print("[mypilot] pairing alert already registered")
        return
    alerts[ALERT_KEY] = ALERT_ENTRY
    with open(ALERTS_PATH, "w") as fh:
        json.dump(alerts, fh, indent=2)
        fh.write("\n")
    print("[mypilot] registered", ALERT_KEY, "in", ALERTS_PATH)


def _base_tag() -> str:
    # frogpilot ships a recognizable marker; default to openpilot otherwise.
    # Spelled out (matches the sunnypilot base's "sunnypilot-" tag) for a readable version string.
    if os.path.isdir("selfdrive/frogpilot") or os.path.exists("frogpilot"):
        return "frogpilot"
    return "openpilot"


def _stamp_version() -> None:
    """Best-effort version rebrand for the experimental root bases: prefix the base tag + append the
    base snapshot date if a simple #define-style version header exists. Skips quietly otherwise (the
    openpilot/frogpilot version scheme isn't guaranteed; a cosmetic must not break the build)."""
    path = next((p for p in VERSION_CANDIDATES if os.path.exists(p)), None)
    if path is None:
        print("[mypilot] version: no known version header on this base; skipping stamp")
        return
    tag = _base_tag()
    with open(path) as fh:
        src = fh.read()
    m = re.search(r'#define\s+(\w*VERSION)\s+"([^"]+)"', src)
    if not m:
        print(f"[mypilot] version: no #define VERSION in {path}; skipping stamp")
        return
    cur = m.group(2)
    if cur.startswith(f"{tag}-"):
        print("[mypilot] version: already stamped")
        return
    # MyPilot version date — auto-derived by assemble.py from the last device-path commit (via env);
    # bumps only on device changes, so it doesn't churn on daily rebuilds.
    mp = os.environ.get("MYPILOT_VERSION", "").strip()
    new_ver = f"{tag}-{cur}-mypilot" + (f"-{mp}" if mp else "")
    with open(path, "w") as fh:
        fh.write(src.replace(m.group(0), m.group(0).replace(f'"{cur}"', f'"{new_ver}"'), 1))
    print(f"[mypilot] version: {cur} -> {new_ver}")


def main() -> int:
    try:
        _stamp_version()
        _register_process()
        _register_pairing_alert()
    except AnchorError as exc:
        print(f"[mypilot] FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
