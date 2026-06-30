#!/usr/bin/env bash
# Regenerate the typed OpenAPI client for the web app from the running API.
# Requires the stack to be up (the API serves /api/openapi.json) and Node/npx locally.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/lib.sh
source scripts/lib.sh

SITE="$(env_get MYPILOT_SITE_ADDRESS localhost)"
SECURE="$(env_get COOKIE_SECURE 0)"
if [[ "$SECURE" == "1" ]]; then SCHEME="https"; else SCHEME="http"; fi
SCHEMA_URL="$SCHEME://$SITE/api/openapi.json"
OUT="mypilot-web/src/lib/api-schema.d.ts"

echo "==> Generating $OUT from $SCHEMA_URL"
if ! command -v npx >/dev/null 2>&1; then
  echo "error: npx (Node.js) is required to generate the client" >&2
  exit 1
fi

npx --yes openapi-typescript "$SCHEMA_URL" -o "$OUT"
echo "==> Done. Commit $OUT after reviewing the diff."
