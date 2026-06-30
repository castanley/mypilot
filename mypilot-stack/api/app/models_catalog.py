"""Curated driving-model catalog (M5).

These mirror the *shape* of openpilot/SunnyPilot driving models (name, generation, runner,
compatibility) so the UI and switch/rollback flow are exercised realistically. The artifacts are
deterministic stand-in blobs — real bytes with a real sha256 the device verifies on switch — not
actual neural-network weights (MyPilot does not touch driving behavior in the control plane).
"""

from __future__ import annotations

import hashlib

# Real driving models are managed on-device by SunnyPilot's Model Manager; MyPilot does not ship
# stand-in artifacts in production (that would be a facade). The catalog is intentionally empty
# until a real model-artifact pipeline is wired — the Models view shows the device's *reported*
# active/installed models instead. Add real entries here (with a real artifact + sha256) to make
# a model switchable from the panel.
# key, name, description, version, generation, runner, device types, default?
MODELS: list[dict] = []

ARTIFACT_SIZE = 8192


def model_artifact(key: str, version: str) -> bytes:
    """Deterministic artifact bytes for a model (stable sha256 across runs)."""
    seed = f"MYPILOT-MODEL::{key}::{version}\n".encode("utf-8")
    body = bytearray()
    while len(body) < ARTIFACT_SIZE:
        body += seed
    return bytes(body[:ARTIFACT_SIZE])


def model_checksum(key: str, version: str) -> str:
    return hashlib.sha256(model_artifact(key, version)).hexdigest()


def model_storage_key(key: str, version: str) -> str:
    return f"models/{key}/{version}/model.bin"
