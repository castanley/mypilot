#!/usr/bin/env python3
"""One-shot LTE speed test during a drive.

Waits until the device is onroad AND the cellular link (ppp0) is up, then runs speedtest-cli ONCE
bound to the cellular source IP (so the test actually goes over LTE, not wifi), records the result +
signal context to /data/mypilot/lte_speedtest_result.json, and exits. Self-terminating; does nothing
to driving. Read the result after the drive:

  ssh comma@<tailscale-ip> 'cat /data/mypilot/lte_speedtest_result.json'
"""

from __future__ import annotations

import json
import os
import subprocess
import time

RESULT = "/data/mypilot/lte_speedtest_result.json"
MODEM_STATE = "/dev/shm/modem"
PARAMS_ONROAD = "/data/params/d/IsOnroad"
WAIT_MINUTES = 90        # give up if no onroad+LTE within this window
SPEEDTEST = "/usr/bin/speedtest-cli"


def _onroad() -> bool:
    try:
        with open(PARAMS_ONROAD, "rb") as f:
            return f.read().strip() == b"1"
    except Exception:  # noqa: BLE001
        return False


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


def _modem() -> dict:
    try:
        with open(MODEM_STATE) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _write(d: dict) -> None:
    d["written_at"] = round(time.time())
    tmp = RESULT + ".tmp"
    try:
        os.makedirs(os.path.dirname(RESULT), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, RESULT)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    start = time.time()
    _write({"status": "waiting", "note": "waiting for onroad + ppp0 up"})

    src = None
    while time.time() - start < WAIT_MINUTES * 60:
        if _onroad():
            src = _ppp_src()
            if src:
                break
        time.sleep(10)

    if not src:
        _write({"status": "gave_up", "note": "no onroad+LTE within window", "onroad": _onroad()})
        return

    m = _modem()
    ctx = {
        "ppp_src": src,
        "registration": m.get("registration"),
        "operator": m.get("operator"),
        "band": m.get("band"),
        "csq": m.get("signal_strength"),
    }
    _write({"status": "running", **ctx})

    # Bind to the cellular source IP so the test traverses LTE (not the wifi default route).
    try:
        r = subprocess.run(
            [SPEEDTEST, "--source", src, "--secure", "--json"],
            capture_output=True, text=True, timeout=180,
        )
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout)
            _write({
                "status": "ok",
                **ctx,
                "download_mbps": round(data.get("download", 0) / 1e6, 2),
                "upload_mbps": round(data.get("upload", 0) / 1e6, 2),
                "ping_ms": round(data.get("ping", 0), 1),
                "server": (data.get("server") or {}).get("sponsor"),
                "server_loc": (data.get("server") or {}).get("name"),
                "bytes_sent": data.get("bytes_sent"),
                "bytes_received": data.get("bytes_received"),
            })
        else:
            _write({"status": "speedtest_failed", **ctx,
                    "rc": r.returncode, "stderr": (r.stderr or "")[:400]})
    except Exception as exc:  # noqa: BLE001
        _write({"status": "error", **ctx, "error": str(exc)[:300]})


if __name__ == "__main__":
    main()
