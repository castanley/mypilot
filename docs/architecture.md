# MyPilot Architecture

MyPilot Stack is a small set of cooperating services deployed with Podman (Docker-compatible).
Everything runs on hardware **you** control. The device keeps driving even if the Stack is down.

## Services

| Service | Image / source | Role |
| --- | --- | --- |
| `mypilot-caddy` | `caddy:2` | Single-origin reverse proxy; `/` → web, `/api/*` → api; auto-TLS for public domains |
| `mypilot-web` | `mypilot-web` (SvelteKit) | Browser control panel |
| `mypilot-api` | `mypilot-stack/api` (FastAPI) | REST + WebSocket: auth, devices, pairing, realtime, health |
| `mypilot-db` | `postgres:16` | Primary datastore |
| `mypilot-redis` | `redis:7` | Presence, pairing-code TTLs, rate limits, pub/sub |
| `mypilot-object-storage` | MinIO | Object storage for logs/routes/backups |

Scaffolded but not started yet: `mypilot-stack/realtime`, `mypilot-stack/ingest`,
`mypilot-stack/worker`, `mypilot-stack/builder`.

## Single-origin model

Caddy serves the web app and the API under **one origin** so the session cookie is
same-origin and CSRF is straightforward. The browser only ever calls `/api/*` on the same host.
Only Caddy (80/443) and the MinIO console (9001) are published; Postgres, Redis, API, and Web
stay on the internal Podman network.

```
browser ──HTTP/WS──> caddy ──/──────> mypilot-web (SSR shell)
                          └──/api/*──> mypilot-api ──> postgres / redis / minio
device  ──HTTP/WS──> caddy ──/api/*──> mypilot-api
```

## Realtime / presence

- The device agent opens `WS /api/realtime/device`, authenticates with an Ed25519-signed
  handshake, then streams heartbeat/status and receives commands.
- Each heartbeat refreshes a Redis presence key `presence:device:{id}` with a short TTL.
  Presence absent ⇒ **offline**.
- The browser opens `WS /api/realtime/web` (cookie auth) and receives presence/status/command
  events, fanned out via Redis pub/sub. A REST heartbeat path exists as a fallback.

## Data ownership & local-first

- Default deployment is **private LAN**. Public internet is possible but opt-in and secured.
- The user chooses what is stored and for how long (retention). Sensitive video is never
  uploaded unless explicitly enabled (see [privacy.md](privacy.md)).

## What is intentionally NOT here

No driving/vehicle-control code and no changes to openpilot/SunnyPilot safety logic. The device
build ([`mypilot-mici`](../mypilot-mici/)) only adds the non-critical MyPilot agent overlay. A
**simulated device** stands in for hardware during local development; the **same agent** runs on a
real comma 4.
