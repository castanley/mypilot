#!/usr/bin/env python3
"""One-off: re-extract GPS tracks for drives whose stored track is TRUNCATED, and re-send them.

Why this exists: a now-fixed bug (commit 0607a53) truncated most drives' GPS track to the first ~60s
segment — the device extracted the track on an early upload cycle (only segment 0 complete), the
server pinned it first-write-wins, and the device burned a one-shot marker so it never re-extracted.
The fix makes future tracks correct and makes the server GROW-ONLY (a fuller track replaces a shorter
one), but the ALREADY-UPLOADED drives still carry their truncated tracks and won't self-heal — the
device has no reason to re-declare a completed route.

This script forces that re-heal for the existing drives: for each route it re-runs the (now-fixed)
extract_route_track over the on-device qlogs and re-POSTs the result through /api/ingest/routes/start.
The server's grow-only _apply_track adopts the new track ONLY if it has more points than what's stored,
so:
  * a truncated route (1 / 0 points) jumps to its full point count, and
  * a route that is already complete (e.g. the healthy multi-segment one) can only grow, never shrink.

It reuses the agent's real signing path + identity so requests are byte-identical to production ingest,
and it is idempotent/re-runnable (grow-only means a second run is a no-op). It sends ONLY the track
metadata via routes/start — it never re-uploads any segment file (the camera/qlog bytes are already in
object storage), so it's cheap and can't OOM.

Run on the device (OFFROAD), same env as recover_backlog.py:
  PYTHONPATH=/data/openpilot/sunnypilot/mypilot /usr/local/venv/bin/python3 \
    /data/backfill_tracks.py --dry-run     # preview old -> new point counts, send nothing
  PYTHONPATH=/data/openpilot/sunnypilot/mypilot /usr/local/venv/bin/python3 \
    /data/backfill_tracks.py               # execute

If a route's qlogs have already rotated off the device, it is reported as un-recoverable locally (its
qlogs survive in object storage; a server-side re-extract would be needed for those).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

from mypilot_agent import drive_video
from mypilot_agent.identity import load_or_create
from mypilot_protocol.signing import build_signed_headers

DATA_DIR = "/data/mypilot"
REALDATA = "/data/media/0/realdata"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

SEG_RE = re.compile(r"^(.+)--(\d+)$")
ROUTE_RE = re.compile(r"^[0-9a-f]{8,}(?:--[0-9a-f]+)*$")
HTTP_TIMEOUT = 120


def _stack_url() -> str:
    cfg = json.load(open(CONFIG_FILE))
    url = (cfg.get("stack_url") or cfg.get("api_base") or "").rstrip("/")
    if not url:
        sys.exit("no stack_url/api_base in config.json")
    return url


def _scan_routes() -> dict[str, list[int]]:
    """Map route_name -> sorted list of segment indices that have a qlog on disk. Only routes whose
    qlogs survive locally can be re-extracted here; the rest need the server-side path."""
    routes: dict[str, list[int]] = {}
    if not os.path.isdir(REALDATA):
        return routes
    for entry in sorted(os.listdir(REALDATA)):
        m = SEG_RE.match(entry)
        if not m:
            continue
        route, seg = m.group(1), int(m.group(2))
        if not ROUTE_RE.match(route):
            continue
        seg_dir = os.path.join(REALDATA, entry)
        has_qlog = any(
            os.path.isfile(os.path.join(seg_dir, n)) for n in ("qlog.zst", "qlog", "qlog.bz2")
        )
        if has_qlog:
            routes.setdefault(route, []).append(seg)
    for r in routes:
        routes[r].sort()
    return routes


class Client:
    def __init__(self, base: str, ident) -> None:
        self.base = base
        self.ident = ident

    def _request(self, method: str, path: str, body: bytes) -> dict:
        headers = build_signed_headers(
            self.ident.device_id, self.ident.private_key_b64, method, path, body
        )
        headers["Content-Type"] = "application/json"
        # Match the agent's UA so Cloudflare's WAF lets it through (urllib's default UA gets 403'd).
        headers["User-Agent"] = "mypilot-agent/backfill aiohttp/3.13.5"
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}

    def route_start_with_track(self, name: str, seg_count: int, track: list) -> dict:
        """Re-declare the route carrying ONLY the freshly-extracted track (no file decls — the files
        are already uploaded). The server reuses the existing route and grow-only-adopts the track."""
        body = json.dumps({
            "name": name,
            "segment_count": seg_count,
            "privacy_state": "logs",
            "files": [],
            "track": track,
        }).encode("utf-8")
        return self._request("POST", "/api/ingest/routes/start", body)


def main() -> None:
    ap = argparse.ArgumentParser(description="Re-extract + re-send truncated drive GPS tracks.")
    ap.add_argument("--dry-run", action="store_true", help="extract + print old->new, send nothing")
    ap.add_argument("--routes", default="", help="comma-separated route names to limit to (default: all on disk)")
    args = ap.parse_args()

    base = _stack_url()
    ident = load_or_create(DATA_DIR)
    if not ident.is_paired:
        sys.exit("device identity is not paired (no device_id)")
    client = Client(base, ident)

    # Point extract_route_track at the real on-device realdata tree.
    drive_video.REALDATA = REALDATA

    routes = _scan_routes()
    only = {r.strip() for r in args.routes.split(",") if r.strip()}
    if only:
        routes = {r: s for r, s in routes.items() if r in only}
    if not routes:
        print("no routes with on-device qlogs found in", REALDATA)
        return

    print(f"stack={base} device={ident.device_id}")
    print(f"{len(routes)} route(s) with local qlogs"
          + ("  --- DRY RUN (nothing sent) ---" if args.dry_run else ""))

    grew = same = failed = 0
    for route, segs in sorted(routes.items()):
        seg_count = len(segs)
        # extract_route_track takes {seg_index: <anything>}; it only iterates sorted(keys).
        track = drive_video.extract_route_track(route, {s: None for s in segs})
        n = len(track) if track else 0
        if not track:
            print(f"route {route}: extracted 0 points from {seg_count} segment(s) "
                  f"(no GPS fixes, or qlogs unreadable) — skipping")
            same += 1
            continue
        max_t = max((p[0] for p in track), default=0.0)
        if args.dry_run:
            print(f"route {route}: {seg_count} seg -> {n} points (max_t={max_t:.0f}s) "
                  f"[would send; server adopts iff > stored]")
            continue
        try:
            resp = client.route_start_with_track(route, seg_count, track)
            stored = resp.get("track_points")
            verdict = ("grew/ok" if stored is None or stored >= n else f"kept stored {stored}")
            print(f"route {route}: sent {n} points (max_t={max_t:.0f}s) -> server now has "
                  f"{stored if stored is not None else '?'} ({verdict})")
            grew += 1
        except urllib.error.HTTPError as exc:
            print(f"route {route}: FAIL HTTP {exc.code} {exc.reason}")
            failed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"route {route}: FAIL {exc}")
            failed += 1

    if not args.dry_run:
        print(f"\ndone: {grew} sent, {same} skipped (no track), {failed} failed")


if __name__ == "__main__":
    main()
