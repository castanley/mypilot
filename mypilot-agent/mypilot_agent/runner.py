"""Agent orchestration: pairing, the realtime WebSocket session, and reconnect handling."""

from __future__ import annotations

import asyncio
import json
import os

import aiohttp
from mypilot_protocol.crypto import sign
from mypilot_protocol.messages import FrameType, ws_auth_message

from . import drive_video, identity as identity_mod
from .backends import make_backend
from .backends.base import DeviceBackend
from .client import StackClient
from .config import AgentConfig
from .identity import Identity
from .mypilotd import _lower_priority
from .uploader import IngestClient


def _collect_uploads_low_prio(mode, cabin):
    """Run the qlog scan/extract in a worker thread, re-asserting the yield-to-driving-stack
    scheduling on THIS thread first. New threads inherit the main thread's SCHED_IDLE + affinity
    by default (verified), so this is belt-and-suspenders — it keeps the one genuinely CPU-heavy
    path (LogReader qlog parsing) at idle priority even if a future refactor changes how/when the
    main thread lowers its own priority. Cheap and idempotent."""
    _lower_priority()
    return drive_video.collect_uploads(mode, cabin)


class NeedsRepair(Exception):
    """Raised when the Stack no longer recognizes this device (e.g. it was revoked)."""


class WSClosed(Exception):
    """Raised when the realtime WebSocket closes, to trigger a reconnect."""


async def _recv_json(ws: aiohttp.ClientWebSocketResponse) -> dict:
    msg = await ws.receive()
    if msg.type in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
        try:
            return json.loads(msg.data)
        except (ValueError, TypeError) as exc:
            # A frame we can't parse is a broken session — surface it as WSClosed so the reconnect
            # loop in run() handles it, rather than letting a ValueError escape and crash the agent.
            raise WSClosed(f"malformed frame: {exc}") from exc
    raise WSClosed(f"websocket closed ({msg.type.name})")


def _print_pairing_code(code: str, expires_at: str) -> None:
    line = "=" * 48
    print(f"\n{line}")
    print("  MyPilot device pairing")
    print("  Enter this code in MyPilot Web -> Devices -> Add device:\n")
    print(f"        ┌{'─' * (len(code) + 6)}┐")
    print(f"        │   {code}   │")
    print(f"        └{'─' * (len(code) + 6)}┘")
    print(f"\n  Expires at: {expires_at}")
    print(f"{line}\n")


async def pair(
    client: StackClient, identity: Identity, cfg: AgentConfig, backend: DeviceBackend
) -> dict:
    """Run the pairing handshake until the device is activated; return the device config.

    The code is shown on the device screen (no SSH needed) via the backend, in addition to the
    console log.
    """
    while True:
        start = await client.register_start(identity)
        pairing_id = start["pairing_id"]
        poll = max(1, int(start.get("poll_interval", 3)))
        _print_pairing_code(start["code"], start["expires_at"])
        # Machine-readable line for scripts/log scraping.
        print(f"[agent] pairing_code={start['code']}", flush=True)
        try:
            backend.show_pairing_code(start["code"], start.get("expires_at"))
        except Exception as exc:  # noqa: BLE001 - display is best-effort
            print(f"[agent] could not show pairing code on screen: {exc}", flush=True)

        while True:
            await asyncio.sleep(poll)
            result = await client.register_complete(pairing_id, identity)
            status = result.get("status")
            if status == "active":
                identity.device_id = result["device_id"]
                identity_mod.save(cfg.data_dir, identity)
                try:
                    backend.clear_pairing_code()
                except Exception:  # noqa: BLE001
                    pass
                print(f"[agent] paired! device id: {identity.device_id}")
                return result.get("config") or {}
            if status == "expired":
                print("[agent] pairing code expired; requesting a new one...")
                break  # restart with a fresh code
            # status == "pending": keep waiting for the user to enter the code


async def backfill_artifacts(
    cfg: AgentConfig, identity: Identity, backend: DeviceBackend, client: IngestClient
) -> None:
    """Upload a sample set of recorded routes + logs once (guarded by a marker file)."""
    marker = os.path.join(cfg.data_dir, "artifacts_uploaded")
    if os.path.exists(marker):
        return
    routes, logs = backend.generate_artifacts()
    for route in routes:
        await client.upload_route(route)
    for log in logs:
        await client.upload_log(log)
    with open(marker, "w") as fh:
        fh.write("done\n")
    print(f"[agent] backfilled {len(routes)} routes and {len(logs)} logs", flush=True)


# Skip an upload cycle when available memory drops below this fraction of total. Drive upload is a
# best-effort sidecar; it must NEVER compete for RAM with the driving stack (camerad et al.). On a
# ~3.6 GB device a runaway upload previously OOM-killed camerad -> "camera malfunction".
_MIN_FREE_MEM_FRACTION = 0.12


def _memory_pressure() -> float | None:
    """Available-memory fraction (0..1) from /proc/meminfo, or None if it can't be read."""
    try:
        info = {}
        with open("/proc/meminfo") as fh:
            for line in fh:
                k, _, rest = line.partition(":")
                info[k] = int(rest.strip().split()[0])  # kB
        total = info.get("MemTotal")
        avail = info.get("MemAvailable")
        if total and avail is not None:
            return avail / total
    except Exception:  # noqa: BLE001
        return None
    return None


async def drive_upload_loop(backend: DeviceBackend, client: IngestClient, interval: int = 120) -> None:
    """Opt-in: periodically ship completed drive segments (qcamera + optional full-res) to the
    stack, and keep comma's OnroadUploads in sync with the toggle. Never raises out — drive upload
    is best-effort and must not kill the session. Files stream from disk (constant memory), and the
    cycle is skipped under memory pressure so egress can never starve the driving stack."""
    params = getattr(backend, "_params", None)
    while True:
        try:
            mode = drive_video.drive_upload_mode()
            cabin = drive_video.cabin_upload_on()
            drive_video.enforce_comma_upload(params, mode, cabin)  # cheap params sync — always
            # Heavy work (segment scan + qlog/LogReader track extraction) is OFFROAD-ONLY: it is
            # CPU+I/O bound and must never run while driving, where it could overrun a heartbeat and
            # contend for the shared cores (a commIssue trigger). Completed segments aren't going
            # anywhere; they ship as soon as the car is parked. Memory-pressure guard still applies.
            if mode != "off" and not backend.onroad:
                free = _memory_pressure()
                if free is not None and free < _MIN_FREE_MEM_FRACTION:
                    print(f"[drive] memory low ({free:.0%} free) — skipping upload cycle", flush=True)
                else:
                    # Run the synchronous scan/extract off the event loop so the WS sender/receiver
                    # stay responsive even offroad; the worker re-asserts idle scheduling first.
                    routes = await asyncio.to_thread(_collect_uploads_low_prio, mode, cabin)
                    for route in routes:
                        # upload_route streams each file and returns the markers that succeeded, so we
                        # persist exactly those — a failed fcamera doesn't block re-marking qcamera,
                        # and successes aren't re-uploaded next cycle (the old churn/OOM source).
                        uploaded = await client.upload_route(route)
                        if uploaded:
                            await asyncio.to_thread(drive_video.mark_uploaded, uploaded)
                            print(f"[drive] uploaded {len(uploaded)} file(s) for route {route['name']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[drive] loop error: {exc}", flush=True)
        await asyncio.sleep(interval)


async def run_session(
    cfg: AgentConfig, identity: Identity, backend: DeviceBackend, config: dict
) -> None:
    """Connect the realtime WebSocket, authenticate, then stream status and handle commands."""
    heartbeat_interval = max(2, int(config.get("heartbeat_interval", 10)))
    # While onroad we stream faster so live driving telemetry (speed/heading/position) stays current
    # instead of jumping every 10s — but keep it modest (4s) so the agent stays a light sidecar and
    # never competes with the driving stack. Offroad keeps the normal (cheaper) interval. Server-overridable.
    onroad_interval = max(2, int(config.get("onroad_heartbeat_interval", 4)))

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(cfg.ws_url, heartbeat=20) as ws:
            # Handshake: receive challenge, respond with a signature over the nonce.
            challenge = await _recv_json(ws)
            if challenge.get("type") != FrameType.AUTH_CHALLENGE.value:
                raise RuntimeError("unexpected handshake frame")
            signature = sign(identity.private_key_b64, ws_auth_message(challenge["nonce"]))
            await ws.send_str(
                json.dumps(
                    {
                        "type": FrameType.AUTH.value,
                        "device_id": identity.device_id,
                        "signature": signature,
                    }
                )
            )
            ack = await _recv_json(ws)
            if ack.get("type") == FrameType.AUTH_FAIL.value:
                raise NeedsRepair(ack.get("reason", "unauthorized"))
            if ack.get("type") != FrameType.AUTH_OK.value:
                raise RuntimeError(f"unexpected auth response: {ack}")
            print(f"[agent] online — streaming status every {heartbeat_interval}s "
                  f"({onroad_interval}s while onroad). Ctrl-C to stop.")

            # Report capabilities + current settings so the web Settings panel populates.
            await ws.send_str(
                json.dumps({"type": FrameType.SETTINGS_SYNC.value, **backend.settings_sync_payload()})
            )

            async def sender() -> None:
                while True:
                    await ws.send_str(
                        json.dumps({"type": FrameType.STATUS.value, "payload": backend.status()})
                    )
                    # Faster cadence while driving so live speed/heading/position don't lag.
                    await asyncio.sleep(onroad_interval if backend.onroad else heartbeat_interval)

            async def receiver() -> None:
                while True:
                    frame = await _recv_json(ws)
                    ftype = frame.get("type")
                    if ftype == FrameType.COMMAND.value:
                        name = frame.get("name")
                        print(f"[agent] command received: {name}")
                        ok, detail = await backend.execute(name, frame.get("args") or {})
                        await ws.send_str(
                            json.dumps(
                                {
                                    "type": FrameType.COMMAND_RESULT.value,
                                    "id": frame.get("id"),
                                    "ok": ok,
                                    "detail": detail,
                                }
                            )
                        )
                        # Commands that change reported state push a fresh snapshot so the Stack
                        # reconciles immediately rather than waiting for the next heartbeat.
                        if ok and name in ("switch_model", "software_update"):
                            await ws.send_str(
                                json.dumps({"type": FrameType.STATUS.value, "payload": backend.status()})
                            )
                        if ok and name == "restore_settings":
                            await ws.send_str(
                                json.dumps(
                                    {"type": FrameType.SETTINGS_SYNC.value, **backend.settings_sync_payload()}
                                )
                            )
                    elif ftype == FrameType.SET_SETTING.value:
                        key = frame.get("key")
                        ok, detail = backend.apply_setting(key, frame.get("value"))
                        await ws.send_str(
                            json.dumps(
                                {
                                    "type": FrameType.SETTING_RESULT.value,
                                    "change_id": frame.get("change_id"),
                                    "key": key,
                                    "ok": ok,
                                    "value": frame.get("value"),
                                    "detail": detail,
                                }
                            )
                        )

            await asyncio.gather(sender(), receiver(), backend.run_state_cycler())


async def run(cfg: AgentConfig) -> None:
    if cfg.reset:
        identity_mod.reset(cfg.data_dir)
    identity = identity_mod.load_or_create(cfg.data_dir, cfg.hardware_id)
    backend = make_backend(cfg, identity)
    client = StackClient(cfg)
    http: IngestClient | None = None
    drive_task: asyncio.Future | None = None
    print(f"[agent] stack: {cfg.api_base}  data-dir: {cfg.data_dir}")

    try:
        config: dict = {}
        if not identity.is_paired:
            config = await pair(client, identity, cfg, backend)

        # Persistent signed HTTP client for artifact upload + model artifact download.
        http = IngestClient(cfg, identity)
        backend.attach_http(http)

        # Opt-in drive-video uploader runs continuously in the background (independent of the WS
        # session reconnect loop), so drives ship even across reconnects.
        drive_task = asyncio.ensure_future(drive_upload_loop(backend, http))

        while True:
            try:
                # One-time backfill of recorded routes/logs (real bytes) over signed HTTP.
                # Marker-guarded, so it succeeds exactly once; retried each connect until the
                # Stack is reachable (handles the agent racing API startup).
                try:
                    await backfill_artifacts(cfg, identity, backend, http)
                except Exception as exc:  # noqa: BLE001 - artifacts are best-effort, never fatal
                    print(f"[agent] artifact backfill deferred: {exc}", flush=True)
                await run_session(cfg, identity, backend, config)
            except NeedsRepair:
                print("[agent] device no longer recognized by the Stack; re-pairing...")
                identity.device_id = None
                identity_mod.save(cfg.data_dir, identity)
                config = await pair(client, identity, cfg, backend)
            except (WSClosed, aiohttp.ClientError, OSError, RuntimeError) as exc:
                # RuntimeError covers an unexpected handshake/auth frame (run_session); like a
                # dropped socket it's session-level, so reconnect rather than crash the agent.
                print(f"[agent] connection lost ({exc}); reconnecting in 5s...")
                await asyncio.sleep(5)
    finally:
        if drive_task is not None:
            drive_task.cancel()
        await client.close()
        if http is not None:
            await http.close()
