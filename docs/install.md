# Installing MyPilot Stack

MyPilot is **Podman-first**. Docker works too. The stack is designed to run on a home server,
Linux VM, NUC, VPS, Unraid, TrueNAS Scale, or a container-capable Synology/QNAP.

## Prerequisites

- Podman 4+ with `podman compose` (or `podman-compose`), **or** Docker with Compose v2.
- ~2 GB RAM and a few GB of disk for the base stack.

## One-command install

```bash
./scripts/install.sh
```

This will:

1. Check that Podman (or Docker) is available.
2. Generate strong random secrets and write a git-ignored `.env` (from `.env.example`).
3. Start the stack with `podman compose up -d --build`.
4. Print the local URL and first-admin setup instructions.

Then open the printed URL (default <http://localhost>) and create your first admin account.

## Manual install

```bash
cp .env.example .env
./scripts/generate-secrets.sh        # fills in random secrets in .env
podman compose up -d --build
```

## Deployment modes

### LAN-only (default)

The default `MYPILOT_CADDY_SITE=:80` makes Caddy serve plain HTTP on port 80 for **any**
host — so the panel works whether you browse via `localhost`, `127.0.0.1`, the host's LAN IP,
or its hostname. Best for a trusted home network. If port 80 is already in use on the host,
set `MYPILOT_HTTP_PORT` (e.g. `8080`) and browse to `http://<host>:8080`.

### Tailscale

Install Tailscale on the host and leave `MYPILOT_CADDY_SITE=:80`. The panel is reachable at
your host's Tailscale MagicDNS name (e.g. `http://my-host.tailnet-name.ts.net`) from any device
on your tailnet, because `:80` matches every host.

### Public domain with automatic TLS

Point a domain's DNS at your host, open 80/443, and set:

```
MYPILOT_CADDY_SITE=mypilot.example.com
COOKIE_SECURE=1
```

Caddy will obtain and renew a certificate automatically and redirect HTTP→HTTPS. Only do this
if you understand the exposure — see [security.md](security.md). Cloudflare Tunnel support is
documented later.

## Updating the stack

```bash
git pull
podman compose build
podman compose up -d
```

Database migrations run automatically on api startup.

## Backups

The Postgres volume (`mypilot_db`) and MinIO volume (`mypilot_minio`) hold your data. Use your
platform's volume backup, or the in-app per-device settings backup/export (Device → **Backups**).

## Uninstall / reset

```bash
podman compose down        # stop, keep data
podman compose down -v     # stop and DELETE all volumes (destructive)
```
