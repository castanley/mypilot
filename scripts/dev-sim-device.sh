#!/usr/bin/env bash
# Run a simulated comma device against the running stack.
# It prints a pairing code to enter in Web -> Devices -> Add device, then keeps
# the device "online" (heartbeats + simulated status) until you press Ctrl-C.
#
# Any extra args are passed through to the agent, e.g.:
#   ./scripts/dev-sim-device.sh --onroad
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh

COMPOSE="$(detect_compose)" || { echo "no compose tool found" >&2; exit 1; }
[[ -f .env ]] || ./scripts/generate-secrets.sh

echo "==> Building the simulated device image..."
# shellcheck disable=SC2086
$COMPOSE --profile sim build mypilot-sim-device

echo "==> Starting simulated device (Ctrl-C to stop)..."
# shellcheck disable=SC2086
exec $COMPOSE --profile sim run --rm mypilot-sim-device "$@"
