# MyPilot — Going Live (production checklist)

This is the production-readiness checklist for running your own MyPilot Stack that real comma 4
devices pair into. Items marked **[done]** are already applied to the reference deployment; **[you]**
items are actions only you can take.

## 1. Auth & secrets
- **[you] Rotate the admin password now.** The bootstrap password (`supersecret123`) is in the
  repo/docs and must be changed: sign in → account menu (top-right) → **Change password**. Changing
  it signs out all other sessions.
- **[done]** Strong, non-default secrets in `.env` (`API_SECRET_KEY`, `POSTGRES_PASSWORD`,
  `MINIO_ROOT_PASSWORD`). Rotating `API_SECRET_KEY` invalidates all sessions (everyone re-logs in).
- **[done]** Login, setup, and pairing are rate-limited (fixed window, per-IP).
- Passwords are Argon2id; sessions are server-side (httpOnly cookie + CSRF double-submit).

## 2. Transport & exposure
- **[done]** `COOKIE_SECURE=1` (session/CSRF cookies carry `Secure`); served over HTTPS behind
  **Cloudflare** (TLS, WAF, DDoS).
- **[done]** MinIO **admin console** is bound to `127.0.0.1:9001` only — never public. Reach it via
  an SSH tunnel: `ssh -L 9001:localhost:9001 <host>` → http://localhost:9001.
- **[you]** Confirm the host firewall only exposes what Cloudflare needs; Postgres/Redis/MinIO API
  and the app stay on the internal compose network (only Caddy is published).
- Security headers present (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`).

## 3. Builds / flashing (real)
- Install on a comma 4 via **Custom Software** (see [comma4-install.md](comma4-install.md)):
  - **release**  → `castanley/mypilot-mici`         (`installer.comma.ai/castanley/mypilot-mici`)
  - **staging**  → `castanley/mypilot-mici-staging`  (RC channel; test before promoting)
- Both URLs resolve through comma's installer (verified). `release-mici` is prebuilt → fast install.
- The Software page shows these as the real channels with their real install URLs.

## 4. Staying current with SunnyPilot
- **[done]** A thin GitHub Action (`sync-mypilot`) on `castanley/openpilot` runs **daily** (and on
  demand). It **clones the public monorepo** and runs `mypilot-mici/publish.sh`, rebuilding each
  `mypilot-*` branch as *latest upstream base + the freshly assembled MyPilot overlay*, pushing only
  what changed.
- **[you]** Keep **Actions enabled** on the delivery repo (GitHub disables fork schedules after long
  inactivity). Trigger manually anytime: Actions → sync-mypilot → Run workflow.
- The overlay's single source of truth is the monorepo (`mypilot-agent` + `mypilot-protocol`),
  assembled by [`mypilot-mici`](../mypilot-mici/).

## 5. Data, privacy, backups
- Driving works even if the Stack is offline; the agent fails closed.
- Route/log upload from the device is **off by default** (privacy); retention sweep is
  admin-configurable (Routes page).
- **[you] Back up regularly:**
  - Postgres: `podman exec mypilot-mypilot-db-1 pg_dump -U mypilot mypilot | gzip > backup.sql.gz`
  - Object storage (MinIO `mypilot` bucket): mirror with `mc` or snapshot the `mypilot_minio` volume.
- Per-device **settings backups** (snapshot/restore/migrate) are in the device **Backups** tab.

## 6. Safety (unchanged, enforced)
- No driving-behavior changes; the agent never touches controlsd/pandad/driver-monitoring/torque.
- Settings/model/software/restore/reboot are **offroad-only**, confirmed, and audited — in the
  agent and the Stack.
- The fork is based on **clean** `release-mici` (no driver-monitoring weakening).

## 7. Monitoring
- Health: `GET /api/health` (database / redis / object_storage).
- Audit: every remote action is recorded (visible per-device under Activity).

## 8. Device-side status
- **Live:** on-screen pairing, telemetry, settings apply/reset, **model switch** (device
  SHA256-verifies before activating), **software update/rollback**, settings restore, reboot — all
  offroad-only and audited.
- **Off by default:** route/log upload from the device (privacy; opt-in).
- **Experimental:** the openpilot and frogpilot install bases are published but not yet validated on
  a physical comma 4 (sunnypilot is the validated default). See
  [mypilot-mici/README.md](../mypilot-mici/README.md).
