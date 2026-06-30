# MyPilot Security & Safety

MyPilot is built like a security-sensitive system. This document describes the controls and the
non-negotiable safety rules.

## Safety rules (never violated)

- **Never** modify, weaken, or bypass openpilot/SunnyPilot safety logic, driver monitoring,
  steering-torque limits, or panda safety hooks. MyPilot adds **no driving code at all** — the agent
  is a non-critical sidecar.
- **No remote control of anything that can affect active driving while onroad.**
- Settings or commands that can affect driving require **offroad** mode, explicit confirmation,
  and an audit record. **Every** such command — settings apply/reset, model switch, software
  update/rollback, settings restore, and reboot — is gated exactly this way.
- The device agent is decoupled from driving-critical processes and **fails closed**: if the
  Stack is unreachable, the device just keeps driving locally.
- Remote shell and remote SSH-key modification are **not** enabled by default.

## User authentication

- First-admin **setup** is a one-time action; it refuses once an admin exists.
- Passwords are hashed with **Argon2id**. Plaintext passwords are never stored or logged.
- Sessions are **server-side** rows; the browser holds an opaque, httpOnly, `SameSite` cookie
  (marked `Secure` when served over TLS).
- State-changing requests require a **CSRF token** issued at login.
- Login and pairing endpoints are **rate-limited** (Redis-backed).

## Device authentication

- The device generates an **Ed25519** keypair locally; the private key never leaves the device.
- Pairing codes are **short-lived**, **one-time**, and **rate-limited**.
- After pairing, every device request is **signed**: `X-MyPilot-Signature` is an Ed25519
  signature over `method\npath\ntimestamp\nsha256(body)`. The server enforces a timestamp
  window (±60s) to prevent replay and verifies against the stored public key.
- Removing/unpairing a device **revokes** its key; subsequent signed requests are rejected.

## Auditing

Every remote action is recorded in `audit_events` with actor, target device, action, and
metadata: login, pairing claim/complete, device alias change, device revoke, every setting change,
model switch, software update/rollback, backup restore, reboot command issuance, and every command
result.

## Secrets handling

- Runtime stack secrets live only in a **git-ignored** `.env`, generated locally.
- We never log credentials, tokens, cookies, device private keys, or pairing codes.
- **SunnyLink inspection credentials (later phase) are never stored** in repo files, `.env`,
  logs, screenshots, HAR exports, browser profiles, terminal history, fixtures, docs, or git
  history. If no secure secret path exists, we ask for sanitized screenshots/recordings instead.

## Network exposure

- Default is **private LAN**. Only Caddy and the MinIO console are published.
- Public deployment is supported but opt-in; use TLS (automatic via Caddy) and consider
  Tailscale or Cloudflare Tunnel rather than exposing ports directly.
