# systemd / autostart (placeholder)

For a server that should bring MyPilot up on boot, run the stack under systemd. Two common
approaches:

1. **Compose as a service** — a simple unit that runs `podman compose up` / `down` in the repo
   directory.
2. **Quadlet** (`.container`/`.network`/`.volume` files in `~/.config/containers/systemd/`) for
   native per-container systemd integration.

Reference unit files will be added here in a later milestone. For now, `scripts/install.sh`
plus `podman compose up -d` is sufficient for a manually managed host.
