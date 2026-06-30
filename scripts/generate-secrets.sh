#!/usr/bin/env bash
# Generate strong random secrets into .env (created from .env.example if missing).
# Idempotent: only replaces values that still contain the CHANGE_ME placeholder.
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".env"
EXAMPLE_FILE=".env.example"

if [[ ! -f "$EXAMPLE_FILE" ]]; then
  echo "error: $EXAMPLE_FILE not found" >&2
  exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$EXAMPLE_FILE" "$ENV_FILE"
  echo "Created $ENV_FILE from $EXAMPLE_FILE"
fi

# URL-safe random string of N bytes (default 32).
rand() {
  local bytes="${1:-32}"
  # base64 then strip non-url-safe chars; good enough entropy from /dev/urandom
  head -c "$bytes" /dev/urandom | base64 | tr -d '/+=\n' | cut -c1-"$((bytes))"
}

# Replace a KEY=...CHANGE_ME... line with a fresh secret. POSIX-safe in-place edit.
set_secret() {
  local key="$1" value="$2"
  if grep -qE "^${key}=.*CHANGE_ME" "$ENV_FILE"; then
    # Use a temp file to avoid sed -i portability issues across GNU/BSD.
    awk -v k="$key" -v v="$value" -F= '
      $1 == k { print k "=" v; next }
      { print }
    ' "$ENV_FILE" > "$ENV_FILE.tmp"
    mv "$ENV_FILE.tmp" "$ENV_FILE"
    echo "  set $key"
  else
    echo "  $key already set, skipping"
  fi
}

echo "Generating secrets in $ENV_FILE ..."
set_secret POSTGRES_PASSWORD "$(rand 32)"
set_secret MINIO_ROOT_PASSWORD "$(rand 32)"
set_secret API_SECRET_KEY "$(rand 48)"

chmod 600 "$ENV_FILE"
echo "Done. $ENV_FILE is git-ignored; keep it private."
