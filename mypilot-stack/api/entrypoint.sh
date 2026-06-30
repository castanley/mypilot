#!/usr/bin/env bash
# Run DB migrations (retrying until Postgres is reachable) then start the API.
set -euo pipefail

echo "[entrypoint] applying database migrations..."
for attempt in $(seq 1 30); do
  if alembic upgrade head; then
    echo "[entrypoint] migrations applied."
    break
  fi
  echo "[entrypoint] database not ready (attempt $attempt/30); retrying in 2s..."
  sleep 2
done

echo "[entrypoint] starting uvicorn..."
# Single worker: the realtime device registry is in-process for M1/M2.
exec uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips='*'
