#!/usr/bin/env python3
"""One-off, memory-safe recovery of the on-device drive backlog.

Why this exists: the agent's drive_upload="full" loop (drive_video.collect_uploads) reads EVERY
not-yet-uploaded segment file fully into RAM in a single list, then aiohttp buffers each body again
to sign it. With ~893 MB of fcamera/ecamera across 27 segments on a 3.6 GB device, that OOMs camerad
("camera malfunction") and then the box. Separately, the server checks Ed25519 timestamp freshness
(60s) only AFTER buffering the whole body, so a tens-of-MB upload that takes >60s over cellular is
rejected 401 even though it transferred fine.

This script sidesteps both, for a manual recovery while on the fast home LAN:
  * ONE file is held in memory at a time (read -> PUT -> drop), so peak RAM is ~one segment file.
  * web-playable files (qcamera.ts, qlog*) upload FIRST, then /complete is called, so the drive is
    viewable in the web immediately; the heavy fcamera/ecamera archive uploads after.
  * each PUT re-signs with a fresh timestamp (build_signed_headers stamps int(time.time()) per call),
    and on LAN every file finishes in <2s, well inside the 60s window.

It reuses the agent's real signing path (mypilot_protocol.signing.build_signed_headers) and identity
(mypilot_agent.identity.load_or_create) so requests are byte-identical to production ingest. It is
idempotent: route_start reuses an existing route, and re-PUTting a file just overwrites the object.

Run on the device:
  PYTHONPATH=/data/openpilot/sunnypilot/mypilot /usr/local/venv/bin/python3 \
    /data/recover_backlog.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from mypilot_agent.identity import load_or_create
from mypilot_protocol.signing import build_signed_headers

DATA_DIR = "/data/mypilot"
REALDATA = "/data/media/0/realdata"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
STATE_FILE = os.path.join(DATA_DIR, "uploaded_segments.json")

# Segment dirs are "<route_name>--<segment_index>". The route name itself contains "--"
# (e.g. "00000000--f5c1a8af3d"), so split on the LAST "--" and validate the route is hex-like —
# that skips junk/test dirs such as "$R--0".
SEG_RE = re.compile(r"^(.+)--(\d+)$")
ROUTE_RE = re.compile(r"^[0-9a-f]{8,}(?:--[0-9a-f]+)*$")

# Upload order: web-playable first (so the drive is viewable ASAP), heavy archive last.
PLAYABLE = ["qcamera.ts", "qlog.zst", "qlog", "qlog.bz2"]
ARCHIVE = ["fcamera.hevc", "ecamera.hevc", "dcamera.hevc"]
KIND = {
    "qcamera.ts": "qcamera", "fcamera.hevc": "fcamera",
    "ecamera.hevc": "ecamera", "dcamera.hevc": "dcamera",
    "qlog.zst": "qlog", "qlog": "qlog", "qlog.bz2": "qlog",
}

# Network timeout per request — generous for the heavy files, but LAN finishes these in <2s.
HTTP_TIMEOUT = 120


def _stack_url() -> str:
    cfg = json.load(open(CONFIG_FILE))
    url = (cfg.get("stack_url") or cfg.get("api_base") or "").rstrip("/")
    if not url:
        sys.exit("no stack_url/api_base in config.json")
    return url


def _segment_complete(seg_dir: str) -> bool:
    """Safe to read only when no .lock files remain (comma removes them when the segment closes)."""
    try:
        return not any(n.endswith(".lock") for n in os.listdir(seg_dir))
    except OSError:
        return False


def _scan() -> dict[str, dict[int, list[str]]]:
    """route_name -> {segment_index -> [filenames present]} for completed segments."""
    out: dict[str, dict[int, list[str]]] = {}
    if not os.path.isdir(REALDATA):
        return out
    wanted = set(PLAYABLE + ARCHIVE)
    for entry in sorted(os.listdir(REALDATA)):
        m = SEG_RE.match(entry)
        if not m:
            continue
        route, seg = m.group(1), int(m.group(2))
        if not ROUTE_RE.match(route):  # skip junk/test dirs like "$R--0"
            continue
        seg_dir = os.path.join(REALDATA, entry)
        if not os.path.isdir(seg_dir) or not _segment_complete(seg_dir):
            continue
        present = [n for n in os.listdir(seg_dir) if n in wanted]
        if present:
            out.setdefault(route, {})[seg] = present
    return out


def _order_files(names: list[str]) -> list[str]:
    """Playable files first (in PLAYABLE order), then archive (in ARCHIVE order)."""
    rank = {n: i for i, n in enumerate(PLAYABLE + ARCHIVE)}
    return sorted(names, key=lambda n: rank.get(n, 999))


def _read_state() -> set[str]:
    try:
        return set(json.load(open(STATE_FILE)))
    except (OSError, ValueError):
        return set()


def _write_state(done: set[str]) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(sorted(done), fh)
    os.replace(tmp, STATE_FILE)


class Client:
    def __init__(self, base: str, ident) -> None:
        self.base = base
        self.ident = ident

    def _request(self, method: str, path: str, body: bytes, ctype: str) -> dict:
        headers = build_signed_headers(
            self.ident.device_id, self.ident.private_key_b64, method, path, body
        )
        headers["Content-Type"] = ctype
        # mypilot.me sits behind Cloudflare, whose WAF 403s the default "Python-urllib/..." UA before
        # the request reaches the API. Use the same UA shape as the agent's aiohttp client, which CF
        # lets through (verified: urllib UA -> 403, aiohttp UA -> 401/200).
        headers["User-Agent"] = "mypilot-agent/recover aiohttp/3.13.5"
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else {}

    def route_start(self, name: str, decls: list[dict], seg_count: int) -> str:
        body = json.dumps({
            "name": name, "segment_count": seg_count, "privacy_state": "logs", "files": decls,
        }).encode("utf-8")
        return self._request("POST", "/api/ingest/routes/start", body, "application/json")["route_id"]

    def put_file(self, route_id: str, seg: int, name: str, body: bytes) -> None:
        path = f"/api/ingest/routes/{route_id}/files/{seg}/{name}"
        self._request("PUT", path, body, "application/octet-stream")

    def complete(self, route_id: str) -> None:
        self._request("POST", f"/api/ingest/routes/{route_id}/complete", b"{}", "application/json")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="list what would upload, send nothing")
    args = ap.parse_args()

    base = _stack_url()
    ident = load_or_create(DATA_DIR)
    if not ident.is_paired:
        sys.exit("device identity is not paired (no device_id)")
    client = Client(base, ident)
    done = _read_state()

    routes = _scan()
    if not routes:
        print("no completed segments found in", REALDATA)
        return

    total_files = sum(len(n) for segs in routes.values() for n in segs.values())
    print(f"stack={base} device={ident.device_id}")
    print(f"{len(routes)} route(s), {total_files} file(s) across {sum(len(s) for s in routes.values())} segment(s)")
    if args.dry_run:
        print("--- DRY RUN (nothing uploaded) ---")

    grand_ok = grand_skip = grand_fail = 0
    for route, segs in sorted(routes.items()):
        # Declare every file up front (segment_index + name + kind), playable-first per segment.
        decls = []
        for seg in sorted(segs):
            for name in _order_files(segs[seg]):
                decls.append({"segment_index": seg, "name": name, "kind": KIND.get(name, "qlog")})
        seg_count = len(segs)

        # Upload order across the whole route: ALL playable files first, then ALL archive files, so
        # the route can be marked complete (viewable) before the heavy archive transfers.
        playable = [(s, n) for s in sorted(segs) for n in _order_files(segs[s]) if n in PLAYABLE]
        archive = [(s, n) for s in sorted(segs) for n in _order_files(segs[s]) if n in ARCHIVE]

        print(f"\nroute {route}: {len(playable)} playable + {len(archive)} archive file(s)")
        if args.dry_run:
            for seg, name in playable + archive:
                marker = f"{route}/{seg}/{name}"
                tag = "skip(done)" if marker in done else "would upload"
                size = os.path.getsize(os.path.join(REALDATA, f"{route}--{seg}", name))
                print(f"  [{tag}] {seg}/{name} ({size/1e6:.1f} MB)")
            continue

        route_id = client.route_start(route, decls, seg_count)
        print(f"  route_id={route_id}")

        def _upload_one(seg: int, name: str) -> str:
            marker = f"{route}/{seg}/{name}"
            if marker in done:
                return "skip"
            path = os.path.join(REALDATA, f"{route}--{seg}", name)
            try:
                with open(path, "rb") as fh:
                    body = fh.read()  # ONE file in memory; dropped at end of scope
                t0 = time.time()
                client.put_file(route_id, seg, name, body)
                dt = time.time() - t0
                print(f"  ok   {seg}/{name} ({len(body)/1e6:.1f} MB, {dt:.1f}s)")
                done.add(marker)
                _write_state(done)  # persist after each file so a crash never re-uploads it
                return "ok"
            except urllib.error.HTTPError as exc:
                print(f"  FAIL {seg}/{name}: HTTP {exc.code} {exc.reason}")
                return "fail"
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL {seg}/{name}: {exc}")
                return "fail"
            finally:
                body = None  # noqa: F841 — explicit drop before next file

        # Playable first, then mark the route complete (viewable), then the heavy archive.
        for seg, name in playable:
            r = _upload_one(seg, name)
            grand_ok += r == "ok"
            grand_skip += r == "skip"
            grand_fail += r == "fail"

        try:
            client.complete(route_id)
            print("  route marked COMPLETE (viewable in web)")
        except Exception as exc:  # noqa: BLE001
            print(f"  WARN could not complete route yet: {exc}")

        for seg, name in archive:
            r = _upload_one(seg, name)
            grand_ok += r == "ok"
            grand_skip += r == "skip"
            grand_fail += r == "fail"

    if not args.dry_run:
        print(f"\ndone: {grand_ok} uploaded, {grand_skip} already-done, {grand_fail} failed")


if __name__ == "__main__":
    main()
