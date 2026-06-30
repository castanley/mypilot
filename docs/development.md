# Developing MyPilot

## Layout

```
mypilot-web/               SvelteKit control panel (TS + Tailwind)
mypilot-stack/api/         FastAPI backend (auth, devices, pairing, realtime, health)
mypilot-stack/{realtime,ingest,worker,builder}/   scaffolds for later milestones
mypilot-agent/             MyPilot Agent (pairing, heartbeat, commands) + simulated backend
mypilot-protocol/          shared Python: Ed25519 sign/verify + message schemas
mypilot-mici/              device build recipe: assembles an upstream base + the agent overlay
deploy/caddy/Caddyfile     single-origin reverse proxy
scripts/                   install / secrets / dev helpers / client generation
```

## Run the stack

```bash
./scripts/install.sh        # first time: secrets + build + up
# or
podman compose up -d --build
podman compose logs -f mypilot-api
```

The api container runs DB migrations on startup. Code is bind-friendly, but the default flow
builds images; rebuild after dependency changes with `podman compose build`.

## Backend

- Python 3.12 inside the container (host Python is not used for app code).
- FastAPI + SQLAlchemy 2.0 async + asyncpg + Alembic + Pydantic v2.
- Run tests **in the container** so versions match:

  ```bash
  podman compose run --rm mypilot-api pytest -q
  ```

- Create a new migration after model changes:

  ```bash
  podman compose run --rm mypilot-api alembic revision --autogenerate -m "describe change"
  ```

## Frontend

- SvelteKit + TypeScript + Tailwind, `@sveltejs/adapter-node`.
- The browser calls same-origin `/api/*` (proxied by Caddy).
- Typed API client is generated from the backend OpenAPI schema:

  ```bash
  ./scripts/gen-client.sh     # writes mypilot-web/src/lib/api-schema.d.ts
  ```

## Simulated device

```bash
./scripts/dev-sim-device.sh           # pair + run a simulated device
python -m mypilot_agent --help        # from mypilot-agent (advanced flags)
```

## Conventions

- Typed APIs everywhere; migrations for all schema changes; OpenAPI as the client source of
  truth.
- Clear service boundaries; prefer boring, reliable infrastructure; don't over-optimize early.
- Tests focus on auth, pairing, settings-safety (later), and command authorization.
- Never log secrets, tokens, cookies, device private keys, or pairing codes.
