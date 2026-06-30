#!/usr/bin/env bash
# Bring the stack up for development (build + follow logs).
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh

COMPOSE="$(detect_compose)" || { echo "no compose tool found" >&2; exit 1; }
[[ -f .env ]] || ./scripts/generate-secrets.sh

# shellcheck disable=SC2086
$COMPOSE up -d --build
# shellcheck disable=SC2086
$COMPOSE logs -f mypilot-api mypilot-web mypilot-caddy
