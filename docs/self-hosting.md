# Self-hosting MyPilot

MyPilot is open source and meant to be self-hosted. Your instance is its own public site: the
landing page at `/` explains the project and links to **Log in** (`/login`); everything else lives
behind auth. This is the quickstart — deeper docs are linked at the end.

## 1. Deploy the stack (Podman-first)

```bash
git clone <your-fork-url> mypilot && cd mypilot
./scripts/install.sh        # checks Podman, generates strong secrets into .env, starts the stack
```

Brings up Postgres, Redis, MinIO, the API, the web app, and Caddy. The installer prints your local
URL. Docker works too (`docker compose up -d --build`), but Podman is first class. Deployment
targets + LAN/Tailscale/TLS: [install.md](install.md).

## 2. First admin

1. Open your URL → you'll land on the public page → **Log in** → first-run **setup**.
2. Create the admin account, then **change the password** (account menu or Settings).

## 3. Configure your deployment (no hard-coding)

Sign in → **Settings**:

- **Project name / Public Stack URL / Source URL** — branding for your landing page.
- **Build / install source** — your GitHub owner + release/staging branches. **Every install URL
  in the panel is derived from these** (shown live), so a fork just sets them here.

Full forking model (the one build-time file + the sync Action): [forking.md](forking.md).

## 4. Put it on the internet (optional, but secure)

Front it with **Cloudflare** or Caddy auto-TLS, set `COOKIE_SECURE=1`, keep the MinIO console on
loopback, and back up Postgres + object storage. The production checklist: [go-live.md](go-live.md).

## 5. Flash a device & pair (no SSH)

1. On the comma 4: **Settings → Software → Custom Software** → enter `your-owner/your-release-branch`.
2. It installs and boots; the **pairing code shows on the device screen**.
3. Enter it at your Stack → **Devices → Add device**. Done.

Device install details + the on-screen pairing: [comma4-install.md](comma4-install.md).

---

### All docs
- [forking.md](forking.md) — fork it; where to change URLs (Settings + `fork.json`)
- [install.md](install.md) — install + deployment targets
- [go-live.md](go-live.md) — production hardening checklist
- [comma4-install.md](comma4-install.md) — flash a comma 4 + pair
- [architecture.md](architecture.md) · [security.md](security.md) · [privacy.md](privacy.md)
