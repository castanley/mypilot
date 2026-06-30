#!/usr/bin/env python3
"""LTE drive speed logger (one-off diagnostic).

Captures cellular throughput + signal during a drive and appends JSON lines to
/data/mypilot/lte_speed.log. Designed to be safe + cheap:

  * PASSIVE by default: samples ppp0's rx/tx byte counters every INTERVAL seconds and reports the
    throughput of whatever traffic is ALREADY flowing (mypilotd's own drive-video upload), so it
    costs ZERO extra data and measures the real-world drive-upload speed.
  * Correlates each sample with signal (CSQ + serving-cell RSRP) and registration (home/roaming),
    so you can see how throughput tracks signal as you move.
  * OPTIONAL small active test (--active) every ACTIVE_EVERY seconds when cellular is connected, for
    a clean down/up number — off by default to avoid burning metered data.

Never raises out; best-effort; exits after MAX_MINUTES so it can't run forever. Read the log after
the drive:  ssh comma@<tailscale-ip> 'cat /data/mypilot/lte_speed.log'
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time

STATE = "/dev/shm/modem"
LOG = "/data/mypilot/lte_speed.log"
PPP_STATS = "/sys/class/net/ppp0/statistics"

INTERVAL = 15          # seconds between samples
MAX_MINUTES = 120      # hard stop
ACTIVE_DL = 3_000_000  # bytes for the optional active download test
ACTIVE_UL = 1_000_000  # bytes for the optional active upload test
ACTIVE_EVERY = 600     # seconds between active tests (when --active)
CF = "104.16.123.96"   # speed.cloudflare.com anycast (literal -> no DNS needed when binding)


def _now() -> float:
    return time.time()


def _modem() -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _ppp_src() -> str | None:
    try:
        r = subprocess.run(["ip", "-4", "addr", "show", "ppp0"], capture_output=True, text=True, timeout=3)
        for line in r.stdout.splitlines():
            p = line.split()
            if "inet" in p:
                return p[p.index("inet") + 1].split("/")[0]
    except Exception:  # noqa: BLE001
        pass
    return None


def _default_iface() -> str:
    try:
        r = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=3)
        first = r.stdout.splitlines()[0] if r.stdout.strip() else ""
        parts = first.split()
        return parts[parts.index("dev") + 1] if "dev" in parts else "?"
    except Exception:  # noqa: BLE001
        return "?"


def _ppp_bytes() -> tuple[int, int]:
    def rd(name: str) -> int:
        try:
            with open(os.path.join(PPP_STATS, name)) as f:
                return int(f.read().strip())
        except Exception:  # noqa: BLE001
            return -1
    return rd("rx_bytes"), rd("tx_bytes")


def _rsrp(m: dict) -> int | None:
    # serving-cell "extra" string: ...,<rsrp>,<rsrq>,<rssi>,... — RSRP is a negative dBm in the 80s-110s.
    extra = m.get("extra") or ""
    cands = []
    for tok in extra.replace('"', "").split(","):
        tok = tok.strip()
        try:
            v = int(tok)
            if -130 <= v <= -40:
                cands.append(v)
        except ValueError:
            continue
    # RSRP is the most-negative of the three signal figures; pick the min of plausible values.
    return min(cands) if cands else None


def _active_test(src: str | None) -> dict:
    """Small bound download+upload over the cellular source IP. Best-effort; returns B/s or None."""
    out: dict = {}
    base = ["curl", "-s", "-o", "/dev/null", "--max-time", "30"]
    if src:
        base += ["--interface", src, "--resolve", f"speed.cloudflare.com:443:{CF}"]
    try:
        r = subprocess.run(
            base + ["-w", "%{speed_download}", f"https://speed.cloudflare.com/__down?bytes={ACTIVE_DL}"],
            capture_output=True, text=True, timeout=35,
        )
        out["dl_Bps"] = int(float(r.stdout.strip() or 0))
    except Exception:  # noqa: BLE001
        out["dl_Bps"] = None
    try:
        payload = b"\0" * ACTIVE_UL
        r = subprocess.run(
            base + ["-w", "%{speed_upload}", "-X", "POST", "--data-binary", "@-", "https://speed.cloudflare.com/__up"],
            input=payload, capture_output=True, timeout=35,
        )
        out["ul_Bps"] = int(float((r.stdout or b"0").decode().strip() or 0))
    except Exception:  # noqa: BLE001
        out["ul_Bps"] = None
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--active", action="store_true", help="also run small active down/up tests (uses data)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    start = _now()
    last_t = start
    last_rx, last_tx = _ppp_bytes()
    last_active = 0.0

    def emit(d: dict) -> None:
        d["t"] = round(_now())
        try:
            with open(LOG, "a") as f:
                f.write(json.dumps(d) + "\n")
        except Exception:  # noqa: BLE001
            pass

    emit({"event": "start", "active": args.active, "interval": INTERVAL})

    while _now() - start < MAX_MINUTES * 60:
        time.sleep(INTERVAL)
        m = _modem()
        rx, tx = _ppp_bytes()
        now = _now()
        dt = max(0.001, now - last_t)
        sample = {
            "event": "sample",
            "registration": m.get("registration"),
            "connected": m.get("connected"),
            "csq": m.get("signal_strength"),
            "rsrp_dbm": _rsrp(m),
            "band": m.get("band"),
            "default_iface": _default_iface(),
            "ppp_up": rx >= 0,
        }
        # passive throughput from byte-counter deltas (only meaningful while ppp0 exists)
        if rx >= 0 and last_rx >= 0:
            sample["rx_kbps"] = round((rx - last_rx) * 8 / dt / 1000, 1)
            sample["tx_kbps"] = round((tx - last_tx) * 8 / dt / 1000, 1)
            sample["tx_total_mb"] = round(tx / 1e6, 1)
        last_rx, last_tx, last_t = rx, tx, now

        # optional active test, spaced out, only when cellular is connected
        if args.active and m.get("connected") and (now - last_active) > ACTIVE_EVERY:
            last_active = now
            sample["active"] = _active_test(_ppp_src())
        emit(sample)

    emit({"event": "stop", "ran_minutes": round((_now() - start) / 60, 1)})


if __name__ == "__main__":
    main()
