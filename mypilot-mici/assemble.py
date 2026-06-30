#!/usr/bin/env python3
"""Assemble the MyPilot device overlay from this monorepo onto an upstream openpilot tree.

The repo's ``mypilot-agent/`` + ``mypilot-protocol/`` are the single source of truth for what runs
on the device; this script vendors them (plus the entrypoint shim and the base-specific
``install_process``) into the overlay directory the chosen base expects. Pure stdlib so it runs
anywhere CI does.

Usage:
  assemble.py plan
      Print one line per channel:  <base> <upstream> <branch> <out> <overlay_dir> <status>
  assemble.py overlay --base <name> --target <dir>
      Write just the overlay into <dir> (used by the byte-identical gate).
  assemble.py build   --base <name> --target <dir>
      Write the overlay and run the base's install_process inside <dir>.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MONO = os.path.dirname(HERE)
RECIPE = os.path.join(HERE, "recipe.json")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info")


def _bases() -> list[dict]:
    with open(RECIPE) as fh:
        return json.load(fh)["bases"]


def _base(name: str) -> dict:
    for b in _bases():
        if b["name"] == name:
            return b
    sys.exit(f"unknown base: {name}")


def _copy_pkg(src: str, dst: str) -> None:
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=IGNORE)


def _copy_files_tree(src_root: str, target: str) -> None:
    """Copy a base's ``files/`` tree (device files at their real relative paths, e.g. the MyPilot
    Link UI) into ``target``, overwriting. Source of truth for files that replace/add to upstream."""
    if not os.path.isdir(src_root):
        return
    for dirpath, _dirs, names in os.walk(src_root):
        for name in names:
            if name.endswith(".pyc") or "__pycache__" in dirpath:
                continue
            src = os.path.join(dirpath, name)
            rel = os.path.relpath(src, src_root)
            dst = os.path.join(target, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            print(f"[assemble]   file -> {rel}")


def build_overlay(base: dict, target: str) -> None:
    overlay = os.path.join(target, base["overlay_dir"])
    if os.path.isdir(overlay):
        shutil.rmtree(overlay)
    os.makedirs(overlay, exist_ok=True)
    # Agent + vendored protocol: the single source of truth, copied verbatim.
    _copy_pkg(os.path.join(MONO, "mypilot-agent", "mypilot_agent"),
              os.path.join(overlay, "mypilot_agent"))
    _copy_pkg(os.path.join(MONO, "mypilot-protocol", "mypilot_protocol"),
              os.path.join(overlay, "mypilot_protocol"))
    # Entrypoint shim + package marker + the base's install_process.
    shutil.copy2(os.path.join(MONO, "mypilot-mici", "overlay", "__init__.py"),
                 os.path.join(overlay, "__init__.py"))
    shutil.copy2(os.path.join(MONO, "mypilot-mici", "overlay", "mypilotd.py"),
                 os.path.join(overlay, "mypilotd.py"))
    shutil.copy2(os.path.join(MONO, base["install_process"]),
                 os.path.join(overlay, "install_process.py"))
    # Base-specific device files (e.g. the MyPilot Link panel + pairing dialog) at their real paths.
    base_dir = os.path.dirname(os.path.join(MONO, base["install_process"]))
    _copy_files_tree(os.path.join(base_dir, "files"), target)
    print(f"[assemble] {base['name']}: overlay -> {overlay}")


# Monorepo paths whose commits actually change the DEVICE build. A commit touching only web/stack/
# docs must NOT bump the device version; a commit touching these SHOULD.
_DEVICE_PATHS = ("mypilot-mici", "mypilot-agent", "mypilot-protocol")


def _mypilot_version() -> str:
    """The MyPilot device version, AUTO-derived from git as ``<date>-<NN>`` (e.g. ``2026.06.26-03``):
      <date> = the date of the last commit that touched a device-affecting path
      <NN>   = how many device-affecting commits landed on that date (a per-day build counter)
    So it reflects real device revisions (not the upstream base date or wall-clock build time → no
    daily publish churn, can't drift from a forgotten manual bump), and the counter ticks up as we
    ship more builds the same day. It's git-derived and therefore reproducible — rebuilding the same
    commit yields the same string (the CI byte-identical gate relies on this). Falls back to empty
    (the stamp then omits the suffix) outside a git tree. Passed to install_process via env."""
    try:
        date = subprocess.check_output(
            ["git", "log", "-1", "--format=%cd", "--date=format:%Y.%m.%d", "--", *_DEVICE_PATHS],
            cwd=MONO, text=True, stderr=subprocess.DEVNULL,
        ).strip()
        if not date:
            return ""
        # Count device-affecting commits whose date == that date (HEAD-most is "this" build).
        dates = subprocess.check_output(
            ["git", "log", "--format=%cd", "--date=format:%Y.%m.%d", "--", *_DEVICE_PATHS],
            cwd=MONO, text=True, stderr=subprocess.DEVNULL,
        ).splitlines()
        count = sum(1 for d in dates if d.strip() == date)
        return f"{date}-{count:02d}"
    except Exception:  # noqa: BLE001 - not a git checkout (e.g. tarball) -> no date
        return ""


def apply_install(base: dict, target: str) -> None:
    script = os.path.join(target, base["overlay_dir"], "install_process.py")
    env = {**os.environ, "MYPILOT_VERSION": _mypilot_version()}
    subprocess.run([sys.executable, script], cwd=target, check=True, env=env)


def apply_private(base: dict, target: str) -> None:
    """Run a base's gitignored private layer if present: ``bases/<name>/private/apply.py`` (cwd=target).

    Private layers carry per-owner, non-publishable assets. They live only on the build machine
    (``bases/*/private/`` is gitignored), so the PUBLIC recipe output stays clean. No-op when absent —
    every published channel builds without it."""
    base_dir = os.path.dirname(os.path.join(MONO, base["install_process"]))
    script = os.path.join(base_dir, "private", "apply.py")
    if not os.path.isfile(script):
        return
    print(f"[assemble] {base['name']}: applying PRIVATE layer ({script})")
    subprocess.run([sys.executable, script], cwd=target, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="list channels for the publisher")
    for cmd in ("overlay", "build"):
        p = sub.add_parser(cmd)
        p.add_argument("--base", required=True)
        p.add_argument("--target", required=True)
        if cmd == "build":
            # Off by default so the public publish pipeline never bakes private assets. A local
            # personal build passes --private to apply that base's private layer.
            p.add_argument("--private", action="store_true",
                           help="also apply the base's gitignored private layer (bases/<name>/private/apply.py)")
    args = ap.parse_args()

    if args.cmd == "plan":
        for b in _bases():
            for ch in b["channels"]:
                print(b["name"], b["upstream"], ch["branch"], ch["out"],
                      b["overlay_dir"], b["status"])
        return

    base = _base(args.base)
    target = os.path.abspath(args.target)
    build_overlay(base, target)
    if args.cmd == "build":
        apply_install(base, target)
        if getattr(args, "private", False):
            apply_private(base, target)


if __name__ == "__main__":
    main()
