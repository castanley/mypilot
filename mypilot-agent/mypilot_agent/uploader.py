"""Signed HTTP upload of recorded routes & logs + model artifact download (aiohttp).

The realtime WebSocket carries small status/command frames; bulk artifacts (drive segment logs,
crash/system logs) and model downloads go over plain authenticated HTTP instead. Each request is
signed with the device's Ed25519 key exactly like the other device-self calls.
"""

from __future__ import annotations

import hashlib
import json
import os

import aiohttp
from mypilot_protocol.signing import build_signed_headers

from .config import AgentConfig
from .identity import Identity

# Read files off disk in chunks so a tens-of-MB segment is never fully held in RAM (the agent runs
# on a ~3.6 GB device; buffering whole files OOM'd camerad). Used for both hashing and streaming.
_CHUNK = 1024 * 1024


def _file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


async def _file_chunks(path: str):
    """Async generator of file chunks for an aiohttp streaming PUT (constant memory)."""
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            yield chunk


class IngestClient:
    def __init__(self, cfg: AgentConfig, identity: Identity) -> None:
        self.cfg = cfg
        self.identity = identity
        self.http = aiohttp.ClientSession()

    async def close(self) -> None:
        await self.http.close()

    def _headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        return build_signed_headers(
            self.identity.device_id, self.identity.private_key_b64, method, path, body
        )

    async def _post_json(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        headers = self._headers("POST", path, body)
        headers["Content-Type"] = "application/json"
        async with self.http.post(self.cfg.api_base + path, data=body, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _put_bytes(self, path: str, body: bytes, content_type: str) -> dict:
        headers = self._headers("PUT", path, body)
        headers["Content-Type"] = content_type
        async with self.http.put(self.cfg.api_base + path, data=body, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _put_file(self, path: str, file_path: str, content_type: str) -> dict:
        """Stream a file from disk: hash it in chunks to sign (body_sha256), then send it chunked so
        the whole file is never buffered in memory. Sets Content-Length so the server reads exactly
        the body and the signed hash matches."""
        digest = _file_sha256(file_path)
        headers = build_signed_headers(
            self.identity.device_id, self.identity.private_key_b64, "PUT", path, body_sha256=digest
        )
        headers["Content-Type"] = content_type
        headers["Content-Length"] = str(os.path.getsize(file_path))
        async with self.http.put(
            self.cfg.api_base + path, data=_file_chunks(file_path), headers=headers
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def download_model(self, model_key: str) -> bytes:
        """Signed GET of a model artifact (the device verifies its sha256 before activating)."""
        path = f"/api/devices/self/models/{model_key}/download"
        headers = self._headers("GET", path, b"")
        async with self.http.get(self.cfg.api_base + path, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.read()

    # Web-playable kinds: these make a drive viewable in the browser, so upload them first and mark
    # the route complete on them — a slow/failing full-res archive must not hide the whole drive.
    _PLAYABLE_KINDS = ("qcamera", "qlog")

    async def upload_route(self, route: dict) -> list[str]:
        """Upload a route's files, streaming each from disk. Resilient + ordered:

          1. declare all files, 2. upload the web-playable ones (qcamera/qlog) first, 3. mark the
             route complete so it's viewable, 4. upload the heavy archive (fcamera/ecamera), 5. mark
             complete again so the size reflects the archive.

        Each file is independent: one failure is logged and skipped, never aborting the rest (so a
        failing fcamera still leaves a viewable drive). Returns the ``_marker`` list of files that
        uploaded successfully, so the caller can persist exactly those as done."""
        decls = [
            {"segment_index": f["segment_index"], "name": f["name"], "kind": f["kind"]}
            for f in route["files"]
        ]
        start = await self._post_json(
            "/api/ingest/routes/start",
            {
                "name": route["name"],
                "alias": route.get("alias"),
                "started_at": route.get("started_at"),
                "ended_at": route.get("ended_at"),
                "duration_s": route.get("duration_s"),
                "distance_m": route.get("distance_m"),
                "segment_count": route.get("segment_count", len(decls)),
                "start_location": route.get("start_location"),
                "end_location": route.get("end_location"),
                "track": route.get("track"),
                "files": decls,
            },
        )
        route_id = start["route_id"]
        playable = [f for f in route["files"] if f["kind"] in self._PLAYABLE_KINDS]
        archive = [f for f in route["files"] if f["kind"] not in self._PLAYABLE_KINDS]

        done: list[str] = []
        # routes/start carried the track; mark it delivered ONLY if the server actually stored what we
        # sent. The server keeps a track only when it's fuller than what it has (grow-only), so a
        # partial track that lost that race comes back with a smaller track_points — leave its marker
        # unset so a later cycle (with the complete drive) re-extracts and re-sends. (The track isn't
        # a file, so this is independent of the per-file uploads below.)
        if route.get("_track_marker"):
            sent = len(route.get("track") or [])
            stored = int(start.get("track_points", 0))
            if stored >= sent:
                done.append(route["_track_marker"])
            else:
                print(f"[drive] track for {route['name']} not fully stored "
                      f"({stored}/{sent} pts) — will retry next cycle", flush=True)
        n_playable = 0
        for f in playable:
            if await self._upload_one(route_id, f):
                n_playable += 1
                if f.get("_marker"):
                    done.append(f["_marker"])
        # Mark viewable as soon as the playable files are up — even if the archive later fails.
        if n_playable:
            await self._complete_quietly(route_id)
        n_archive = 0
        for f in archive:
            if await self._upload_one(route_id, f):
                n_archive += 1
                if f.get("_marker"):
                    done.append(f["_marker"])
        if n_archive:
            await self._complete_quietly(route_id)  # idempotent; refresh size to include the archive
        elif not n_playable:
            # Nothing uploaded at all but the route was declared — still try to close it out cleanly.
            await self._complete_quietly(route_id)
        return done

    async def _upload_one(self, route_id: str, f: dict) -> bool:
        """Upload one segment file. Streams from disk when the file carries a ``path`` (real device,
        constant memory) or sends in-memory ``data`` bytes (simulated backend). Returns True on
        success; logs and returns False on failure so the loop continues with the rest of the route."""
        path = f"/api/ingest/routes/{route_id}/files/{f['segment_index']}/{f['name']}"
        label = f.get("_marker") or f"{f['segment_index']}/{f['name']}"
        try:
            if f.get("path") is not None:
                await self._put_file(path, f["path"], "application/octet-stream")
            else:
                await self._put_bytes(path, f["data"], "application/octet-stream")
            return True
        except Exception as exc:  # noqa: BLE001 - one file failing must not abort the route
            print(f"[drive] upload failed for {label}: {exc}", flush=True)
            return False

    async def _complete_quietly(self, route_id: str) -> None:
        try:
            await self._post_json(f"/api/ingest/routes/{route_id}/complete", {})
        except Exception as exc:  # noqa: BLE001
            print(f"[drive] route complete failed for {route_id}: {exc}", flush=True)

    async def upload_log(self, log: dict) -> str:
        start = await self._post_json(
            "/api/ingest/logs/start",
            {"kind": log["kind"], "name": log["name"], "route_name": log.get("route_name")},
        )
        log_id = start["id"]
        ctype = "text/plain" if log["kind"] == "crash" else "application/octet-stream"
        await self._put_bytes(f"/api/ingest/logs/{log_id}/content", log["data"], ctype)
        return log_id
