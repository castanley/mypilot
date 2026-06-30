#!/usr/bin/env bash
# Shared helpers for MyPilot scripts. Source this; do not execute directly.

# Detect a working compose command. Prefers Podman (first class), falls back to Docker.
# Echoes the command (e.g. "podman compose"); returns non-zero if none found.
detect_compose() {
  if command -v podman >/dev/null 2>&1; then
    if podman compose version >/dev/null 2>&1; then
      echo "podman compose"; return 0
    fi
    if command -v podman-compose >/dev/null 2>&1; then
      echo "podman-compose"; return 0
    fi
  fi
  if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
      echo "docker compose"; return 0
    fi
    if command -v docker-compose >/dev/null 2>&1; then
      echo "docker-compose"; return 0
    fi
  fi
  return 1
}

# Read a KEY=value from .env (no quoting/expansion). Usage: env_get KEY [default]
env_get() {
  local key="$1" default="${2:-}"
  if [[ -f .env ]] && grep -qE "^${key}=" .env; then
    grep -E "^${key}=" .env | head -n1 | cut -d= -f2-
  else
    printf '%s' "$default"
  fi
}
