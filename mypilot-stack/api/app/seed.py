"""Seed catalogs (idempotent upsert): settings, driving models, software releases."""

from __future__ import annotations

import json
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import storage
from .models import DangerLevel, Model, SettingDefinition, SettingType, SoftwareRelease
from .models_catalog import MODELS, model_artifact, model_checksum, model_storage_key
from .settings_catalog import SETTINGS
from .software_catalog import RELEASES


def _extra_settings() -> list[dict]:
    """Optional deployment-specific settings, merged on top of the built-in catalog.

    An operator can add their own settings by pointing ``MYPILOT_EXTRA_SETTINGS`` at a JSON file
    containing a list of catalog entries (same shape as ``settings_catalog.SETTINGS``). This repo
    ships no such file and sets no such env var, so a default deployment merges nothing. Same
    fork-knob philosophy as fork.json: config-as-data, not code.
    """
    path = os.environ.get("MYPILOT_EXTRA_SETTINGS")
    if not path:
        return []
    try:
        with open(path) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001 - a missing/garbled overlay must never break seeding
        return []


def _infer_type(entry: dict) -> str:
    if entry.get("type"):
        return entry["type"]
    if entry.get("options"):
        return SettingType.ENUM
    dv = entry.get("default")
    if isinstance(dv, bool):
        return SettingType.BOOLEAN
    if isinstance(dv, (int, float)):
        return SettingType.NUMBER
    return SettingType.STRING


def normalized_defs() -> list[dict]:
    out = []
    # Built-in catalog first, then any deployment-specific additions (later entries override
    # earlier ones with the same key via the dedup below).
    catalog = list(SETTINGS) + _extra_settings()
    seen: dict[str, int] = {}
    for i, e in enumerate(catalog):
        norm = {
                "key": e["key"],
                "type": _infer_type(e),
                "label": e["label"],
                "description": e.get("description", ""),
                "options": e.get("options"),
                "default_value": e.get("default"),
                "min_value": e.get("min"),
                "max_value": e.get("max"),
                "step": e.get("step"),
                "panel": e["panel"],
                "section": e.get("section"),
                "order": e.get("order", i),
                "requires_offroad": bool(e.get("requires_offroad", False)),
                "requires_reboot": bool(e.get("requires_reboot", False)),
                "danger_level": e.get("danger", DangerLevel.SAFE),
                "remote_configurable": bool(e.get("remote_configurable", True)),
                "capability": e.get("capability"),
                "arm_on_device_only": bool(e.get("arm_on_device_only", False)),
            }
        if e["key"] in seen:
            out[seen[e["key"]]] = norm  # overlay overrides a public entry with the same key
        else:
            seen[e["key"]] = len(out)
            out.append(norm)
    return out


async def seed_settings(session: AsyncSession) -> int:
    defs = normalized_defs()
    for d in defs:
        await session.merge(SettingDefinition(**d))
    await session.commit()
    return len(defs)


async def seed_models(session: AsyncSession) -> int:
    """Upsert the model catalog, ensure each artifact is in storage, and prune stale models.

    With an empty catalog (production default) this removes any previously-seeded models + their
    object-storage artifacts, leaving the Models view to reflect device-reported models only.
    """
    keys = {e["key"] for e in MODELS}
    for entry in MODELS:
        key = entry["key"]
        version = entry["version"]
        checksum = model_checksum(key, version)
        storage_key = model_storage_key(key, version)
        artifact = model_artifact(key, version)

        existing = (
            await session.execute(select(Model).where(Model.key == key))
        ).scalar_one_or_none()
        if existing is None or existing.checksum != checksum:
            await storage.put_object(storage_key, artifact, "application/octet-stream")
        if existing is None:
            session.add(
                Model(
                    key=key,
                    name=entry["name"],
                    description=entry.get("description", ""),
                    version=version,
                    generation=entry.get("generation"),
                    runner=entry.get("runner"),
                    checksum=checksum,
                    size_bytes=len(artifact),
                    storage_key=storage_key,
                    compatible_device_types=entry.get("compatible_device_types", []),
                    compatible_versions=entry.get("compatible_versions", []),
                    is_default=bool(entry.get("is_default", False)),
                )
            )
        else:
            existing.name = entry["name"]
            existing.description = entry.get("description", "")
            existing.version = version
            existing.generation = entry.get("generation")
            existing.runner = entry.get("runner")
            existing.checksum = checksum
            existing.size_bytes = len(artifact)
            existing.storage_key = storage_key
            existing.compatible_device_types = entry.get("compatible_device_types", [])
            existing.is_default = bool(entry.get("is_default", False))

    # Prune models no longer in the catalog (e.g. removed stand-ins) + their artifacts.
    for m in (await session.execute(select(Model))).scalars().all():
        if m.key not in keys:
            if m.storage_key:
                try:
                    await storage.delete_object(m.storage_key)
                except Exception:  # noqa: BLE001
                    pass
            await session.delete(m)
    await session.commit()
    return len(MODELS)


async def seed_releases(session: AsyncSession) -> int:
    """Upsert the software-release catalog (keyed by version) and prune stale rows."""
    versions = {e["version"] for e in RELEASES}
    for entry in RELEASES:
        existing = (
            await session.execute(
                select(SoftwareRelease).where(SoftwareRelease.version == entry["version"])
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                SoftwareRelease(
                    version=entry["version"],
                    channel=entry["channel"],
                    notes=entry.get("notes", ""),
                    install_url=entry.get("install_url"),
                    is_current=bool(entry.get("is_current", False)),
                )
            )
        else:
            existing.channel = entry["channel"]
            existing.notes = entry.get("notes", "")
            existing.install_url = entry.get("install_url")
            existing.is_current = bool(entry.get("is_current", False))

    # Prune releases no longer in the catalog (e.g. the old placeholder versions).
    for r in (await session.execute(select(SoftwareRelease))).scalars().all():
        if r.version not in versions:
            await session.delete(r)
    await session.commit()
    return len(RELEASES)
