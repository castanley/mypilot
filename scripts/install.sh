#!/usr/bin/env bash
# Guided installer for the MyPilot Stack.
#   1. check for Podman/Docker compose   2. generate secrets   3. create .env
#   4. start the stack                   5. print URL + first-admin instructions
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh

echo "==> MyPilot installer"

# 1. Compose runtime ----------------------------------------------------------
if ! COMPOSE="$(detect_compose)"; then
  cat >&2 <<'EOF'
error: no container compose tool found.

Install Podman (recommended) with the compose plugin, or Docker with Compose v2:
  - Podman:  https://podman.io/docs/installation   (then `podman compose version`)
  - Docker:  https://docs.docker.com/compose/install/
EOF
  exit 1
fi
echo "    using: $COMPOSE"

# 2 + 3. Secrets and .env -----------------------------------------------------
./scripts/generate-secrets.sh

# 4. Start the stack ----------------------------------------------------------
echo "==> Building images and starting the stack (this can take a few minutes)..."
# shellcheck disable=SC2086
$COMPOSE up -d --build

# 5. Print URL + next steps ---------------------------------------------------
SITE="$(env_get MYPILOT_SITE_ADDRESS localhost)"
SECURE="$(env_get COOKIE_SECURE 0)"
if [[ "$SECURE" == "1" || ( "$SITE" != "localhost" && "$SITE" != 127.0.0.1 ) ]]; then
  SCHEME="https"
else
  SCHEME="http"
fi
URL="$SCHEME://$SITE"

cat <<EOF

============================================================
  MyPilot Stack is starting.

  Open:   $URL

  Next steps:
    1. Create your first admin account on the setup screen.
    2. Pair the simulated device:
         ./scripts/dev-sim-device.sh
       Enter the printed code in Web -> Devices -> Add device.

  Useful commands:
    $COMPOSE ps           # service status
    $COMPOSE logs -f       # follow logs
    $COMPOSE down          # stop (keep data)

  The MinIO console (admin) is bound to loopback only (127.0.0.1:9001) — never exposed publicly.
  Reach it via an SSH tunnel:  ssh -L 9001:localhost:9001 <this-host>  then open http://localhost:9001
============================================================
EOF
