# Docker deployment notes

Docker is supported for compatibility (Podman is first class). The same root `compose.yaml`
works with Docker Compose v2:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f
docker compose down
```

If you use Docker, set `COMPOSE="docker compose"` for the Makefile targets:

```bash
make up COMPOSE="docker compose"
```
