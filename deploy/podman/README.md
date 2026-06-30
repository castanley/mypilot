# Podman deployment notes

Podman is the **first-class** runtime for MyPilot. The root `compose.yaml` works with both
`podman compose` (the Docker-compose provider) and `podman-compose`.

```bash
podman compose up -d --build     # start
podman compose ps                # status
podman compose logs -f           # logs
podman compose down              # stop (keep volumes)
```

## Rootless

The stack runs fine rootless. Binding ports 80/443 rootless may require:

```bash
sudo sysctl net.ipv4.ip_unprivileged_port_start=80
```

or run Caddy on high ports and front it with your own proxy / `slirp4netns` port mapping.

## Autostart (systemd)

Generate user units from running containers, or use the Quadlet files described in
`../systemd/`.
