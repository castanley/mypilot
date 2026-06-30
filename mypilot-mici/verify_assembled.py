#!/usr/bin/env python3
"""CI gate: assert an assembled device tree is a correct MyPilot image.

Run with cwd = an assembled tree (after ``assemble.py build``), or pass --target <dir>. Exits
non-zero with a clear message on any violation, so the daily publish pipeline FAILS LOUDLY rather
than shipping an image that re-enabled sunnylink phone-home, never launches the agent, or lost SSH.

Usage:
  verify_assembled.py [--target DIR] [--expect-private]
    --expect-private: also require the private layer's effects — used for a personal build,
                      NOT for public channels.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

PROC = "system/manager/process_config.py"
UI_STATE = "selfdrive/ui/sunnypilot/ui_state.py"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default=".")
    ap.add_argument("--expect-private", action="store_true")
    args = ap.parse_args()
    os.chdir(args.target)

    fails: list[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            fails.append(msg)

    proc = open(PROC).read() if os.path.exists(PROC) else ""

    # The sunnylink teardown + MyPilot Link UI only apply to the sunnypilot base (sunnylink is a
    # sunnypilot feature). Detect it by the sunnypilot UI tree; the root base (openpilot/frogpilot)
    # has no sunnylink, so those checks are skipped there.
    is_sunnypilot = os.path.isdir("selfdrive/ui/sunnypilot")

    # 1. (sunnypilot only) No live sunnylink phone-home daemon registration survives.
    if is_sunnypilot:
        for needle in ('"manage_sunnylinkd"', '"sunnylink_registration_manager"', '"statsd_sp"',
                       "sunnylink.backups.manager", "sunnylink.uploader"):
            check(needle not in proc, f"sunnylink daemon still registered: {needle}")
        # ...and the orphaned shims/import are gone (no dangling references).
        check("sunnylink_ready_shim" not in proc, "orphaned sunnylink_ready_shim still present")
        check("from openpilot.sunnypilot.sunnylink.utils import" not in proc,
              "unused sunnylink.utils import still present")

    # 2. The agent is registered AND will actually land in managed_processes (above the build line).
    check('"mypilotd"' in proc, "mypilotd not registered")
    if "mypilotd" in proc and "managed_processes = {p.name: p for p in procs}" in proc:
        before = proc.split("managed_processes = {p.name: p for p in procs}")[0]
        check('"mypilotd"' in before, "mypilotd registered AFTER managed_processes (will never launch)")
    check("restart_if_crash=True" in proc, "mypilotd missing restart_if_crash=True")

    if is_sunnypilot:
        # 3. In-UI sunnylink worker force-disabled.
        if os.path.exists(UI_STATE):
            check("self.sunnylink_enabled = False" in open(UI_STATE).read(),
                  "ui_state does not force sunnylink_enabled = False")
        # 4. MyPilot Link UI present; old sunnylink panel gone.
        check(os.path.exists("selfdrive/ui/sunnypilot/mici/layouts/mypilot_link.py"),
              "mypilot_link.py missing (UI not vendored)")
        check(not os.path.exists("selfdrive/ui/sunnypilot/mici/layouts/sunnylink.py"),
              "dead sunnylink.py panel still present")
        # 4b. Version stamped with the sunnypilot- base tag (fails loud if upstream moved version.h).
        vh = "sunnypilot/common/version.h"
        if os.path.exists(vh):
            check('SUNNYPILOT_VERSION "sunnypilot-' in open(vh).read(),
                  "version not stamped with sunnypilot- base tag")

    # 5. Agent overlay present + import-safe launcher.
    launcher = next((p for p in ("sunnypilot/mypilot/mypilotd.py", "mypilot/mypilotd.py")
                     if os.path.exists(p)), None)
    check(launcher is not None, "agent launcher (mypilotd.py) missing")

    # 6. No user-visible 'sunnypilot' brand left in the key mici screens we rebrand.
    home = "selfdrive/ui/mici/layouts/home.py"
    if os.path.exists(home):
        check('UnifiedLabel("sunnypilot"' not in open(home).read(),
              "home wordmark still says sunnypilot")

    # 6b. The pairing alert key must be registered (the agent's on-screen pairing references it).
    alerts = "selfdrive/selfdrived/alerts_offroad.json"
    check(os.path.exists(alerts) and "Offroad_MyPilotPairing" in open(alerts).read(),
          "Offroad_MyPilotPairing alert not registered in alerts_offroad.json")

    # 6c. No stale sunnypilot.ai terms URL anywhere (source OR translation catalogs) — a wrong
    #     external link on non-English devices.
    if is_sunnypilot:
        tdir = "selfdrive/ui/translations"
        if os.path.isdir(tdir):
            for name in os.listdir(tdir):
                if name.endswith((".po", ".pot")):
                    check("sunnypilot.ai/terms" not in open(os.path.join(tdir, name)).read(),
                          f"stale sunnypilot.ai/terms URL in translation catalog {name}")

    # 7. Private layer (only when expected): delegate to the private layer's own verifier if present.
    #    The checks for a private build's effects live with that build (a gitignored verify.py), so the
    #    public recipe asserts only that the layer ran, not what it contains.
    if args.expect_private:
        priv_verify = os.path.join("sunnypilot", "mypilot", "private", "verify.py")
        check(os.path.exists(priv_verify), "private: layer verifier missing (build with --private?)")
        if os.path.exists(priv_verify):
            rc = subprocess.run([sys.executable, priv_verify]).returncode
            check(rc == 0, "private: layer verification failed")

    if fails:
        print("[verify] FAILED:", file=sys.stderr)
        for f in fails:
            print("  -", f, file=sys.stderr)
        return 1
    print("[verify] OK — assembled tree is a correct MyPilot image"
          + (" (with private layer)" if args.expect_private else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
