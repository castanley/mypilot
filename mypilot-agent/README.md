# mypilotd — the MyPilot device agent

`mypilotd` is the small, **non-critical** agent that runs on a comma device (or a dev machine) and
connects it to a self-hosted MyPilot Stack. It does three things:

1. **Pairs** the device to your Stack (one-time, code-based).
2. **Streams telemetry** + handles commands/settings over a realtime WebSocket.
3. **Uploads drives** (opt-in) over signed HTTP.

It is a sidecar: it **never touches driving**. No control, panda, or driver-monitoring code; it can't
block boot or affect the car. On a real device it degrades to a no-op rather than ever raising into
the host.

## Quick start (dev / simulated)

```bash
# from the repo root
pip install ./mypilot-protocol && pip install -r mypilot-agent/requirements.txt
python -m mypilot_agent --stack-url http://localhost      # simulated device, data in ~/.mypilot/agent
python -m mypilot_agent --stack-url http://localhost --onroad   # start onroad
python -m mypilot_agent --stack-url http://localhost --cycle    # walk through states for the UI
```

Docker (also the simulated device):

```bash
podman build -f mypilot-agent/Dockerfile -t mypilot-agent .   # or docker build …
```

On a **real comma device** you don't run it by hand — openpilot's process manager launches it via the
import-safe shim `mypilot-mici/overlay/mypilotd.py`, which calls `mypilot_agent.mypilotd.main()`.

## Architecture / lifecycle

`runner.run()` is the state machine (see `runner.py`):

```
load/create identity ──▶ paired? ──no──▶ pair() until active ──┐
                                                               ▼
            ┌───────────────────────────────────────────────────────────┐
            │  loop:  backfill artifacts once (marker-guarded)           │
            │         run_session()  ── WS: auth → stream status,        │
            │                           handle commands + settings       │
            │  on drop/RuntimeError → reconnect (5s);                     │
            │  on NeedsRepair       → re-pair                             │
            └───────────────────────────────────────────────────────────┘
   ▲ a background drive-upload loop runs the whole time, independent of reconnects
```

## Module map

| File | Role |
|---|---|
| `mypilotd.py` | on-device entry: resolves stack URL + config, then `runner.run()` |
| `__main__.py` | dev entry (`python -m mypilot_agent`): parse CLI → `runner.run()` |
| `runner.py` | orchestration: pair, the WS session, reconnect loop, drive-upload loop |
| `config.py` | `AgentConfig` + CLI/env parsing |
| `identity.py` | persistent Ed25519 keypair + hardware id |
| `client.py` | pairing HTTP calls to the Stack |
| `uploader.py` | signed HTTP client for artifact upload + model download |
| `drive_video.py` | opt-in drive-segment upload (off/qcamera/full) |
| `backends/base.py` | `DeviceBackend` ABC — the device contract |
| `backends/real.py` | real openpilot-backed device (Params, cereal, Model Manager) |
| `backends/simulated.py` | a self-contained fake device for dev |

The agent↔Stack wire shapes (telemetry envelope, frame types, request signing) live in the shared
`mypilot-protocol/` package — read `mypilot_protocol/telemetry.py` for the telemetry contract.

## Backend selection

`SimulatedDevice` is the **default**. `--real` (or env `MYPILOT_AGENT_REAL=1`) loads `RealDevice`,
which needs openpilot importable — so it's for on-device use; all its openpilot imports are lazy and
fall back to `None`, so importing the package on a dev machine never fails.

## Configuration precedence

The Stack URL is resolved (on-device, in `mypilotd.py`):

```
MYPILOT_STACK_URL env  >  /data/mypilot/config.json  >  fork.json (build-time default)  >  http://localhost
```

`fork.json` (vendored into each build) is the one file a fork edits to point at its own Stack. In dev,
`--stack-url` / `MYPILOT_STACK_URL` is all you need.

## Prebuilt-device constraints (why some code looks defensive)

The device runs a **prebuilt** openpilot — `params_pyx.so` is compiled in, so you **cannot add new
Params keys** (writing an undeclared key raises `UnknownKeyName`). Consequences you'll see in the code:

- MyPilot-owned settings live in **`/data/mypilot/config.json`**, not Params (`drive_video.py`).
- We only read/write **already-declared** params (e.g. `OnroadUploads`), and `Params.get()` returns
  bytes/str with no `encoding=` kwarg (`real.py._param_str`).
- Car identity comes from the `CarParams` capnp struct with a multi-key fallback (`real.py._platform`).
- Every openpilot import is lazy and degrades to `None`; broad excepts are intentional (a sidecar must
  never crash the host).

## Data directory

Dev: `~/.mypilot/agent/` · on-device: `/data/mypilot/`.

| File | What |
|---|---|
| `identity.json` | persistent Ed25519 keypair + hardware id (0600) |
| `config.json` | MyPilot-owned settings (stack_url, drive_upload, owner toggles) |
| `pairing.json` | the active pairing code, for the on-screen display |
| `uploaded_segments.json` | dedupe markers so drive upload resumes across reboots |
| `artifacts_uploaded` | one-time backfill marker |

## Adding a command

Implement it in a backend's `execute(name, args)` (`backends/base.py`), using the names in
`mypilot_protocol.messages.CommandName`. The simulated backend is the worked example. State-changing
commands must be refused while onroad.
