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
# --forwarded-allow-ips is which upstream peers uvicorn will honor X-Forwarded-* from. It defaults to
# '*' (trust any peer) so a standalone self-hosted deploy behind its own single reverse proxy works
# out of the box. A deployment that fronts the API with a known proxy can pin MYPILOT_FORWARDED_ALLOW_IPS
# to just that proxy's address/subnet to reject forwarded headers from anything else (defense in depth).
exec uvicorn app.main:app \
  --host 0.0.0.0 --port 8000 \
  --proxy-headers --forwarded-allow-ips="${MYPILOT_FORWARDED_ALLOW_IPS:-*}"
