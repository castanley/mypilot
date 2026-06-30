"""Settings backups: snapshot -> JSON in object storage, diff, and offroad-gated restore (M6).

A backup is a JSON document of a device's current setting values. Restore re-applies those values
to a (possibly different) device via a single ``restore_settings`` command — enabling
device-to-device migration. Restores are offroad-only and audited.
"""

from __future__ import annotations

import hashlib
import json

from fastapi import HTTPException, status
from mypilot_protocol.messages import CommandName
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import record_audit
from .models import (
    Backup,
    BackupKind,
    CommandStatus,
    Device,
    DeviceCommand,
    DeviceSetting,
    DeviceStatus,
    SettingDefinition,
)
from .schemas import BackupDiffEntry, BackupDiffResponse

BACKUP_VERSION = 1


def _backup_key(device_id: str | None, backup_id: str) -> str:
    return f"backups/{device_id or 'shared'}/{backup_id}.json"


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


async def _current_settings(db: AsyncSession, device_id: str) -> dict:
    rows = (
        await db.execute(select(DeviceSetting).where(DeviceSetting.device_id == device_id))
    ).scalars().all()
    return {r.key: r.value for r in rows}


async def create_backup(
    db: AsyncSession,
    storage_mod,
    user_id: int,
    device: Device,
    name: str | None,
    note: str | None,
    ip: str | None,
) -> Backup:
    settings = await _current_settings(db, device.id)
    backup = Backup(
        device_id=device.id,
        name=name or f"{device.alias} settings",
        kind=BackupKind.SETTINGS,
        note=note,
        source_alias=device.alias,
        settings_count=len(settings),
        created_by=user_id,
    )
    db.add(backup)
    await db.flush()  # assign id

    payload = {
        "mypilot_backup_version": BACKUP_VERSION,
        "kind": BackupKind.SETTINGS,
        "device_id": device.id,
        "source_alias": device.alias,
        "settings": settings,
        "capabilities": device.capabilities or {},
    }
    body = _canonical(payload)
    key = _backup_key(device.id, backup.id)
    await storage_mod.put_object(key, body, "application/json")
    backup.storage_key = key
    backup.size_bytes = len(body)
    backup.checksum = hashlib.sha256(body).hexdigest()

    await record_audit(
        db,
        action="device.backup.create",
        actor_type="user",
        actor_id=str(user_id),
        device_id=device.id,
        metadata={"backup_id": backup.id, "settings_count": len(settings)},
        ip=ip,
    )
    await db.commit()
    await db.refresh(backup)
    return backup


async def create_from_upload(
    db: AsyncSession,
    storage_mod,
    user_id: int,
    raw: bytes,
    ip: str | None,
) -> Backup:
    try:
        doc = json.loads(raw)
        assert isinstance(doc, dict)
        settings = doc.get("settings")
        assert isinstance(settings, dict)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid backup file")

    backup = Backup(
        device_id=None,
        name=(doc.get("source_alias") or "Imported") + " settings (imported)",
        kind=BackupKind.SETTINGS,
        source_alias=doc.get("source_alias"),
        settings_count=len(settings),
        created_by=user_id,
    )
    db.add(backup)
    await db.flush()
    payload = {
        "mypilot_backup_version": BACKUP_VERSION,
        "kind": BackupKind.SETTINGS,
        "device_id": doc.get("device_id"),
        "source_alias": doc.get("source_alias"),
        "settings": settings,
        "capabilities": doc.get("capabilities", {}),
    }
    body = _canonical(payload)
    key = _backup_key(None, backup.id)
    await storage_mod.put_object(key, body, "application/json")
    backup.storage_key = key
    backup.size_bytes = len(body)
    backup.checksum = hashlib.sha256(body).hexdigest()
    await record_audit(
        db, action="backup.import", actor_type="user", actor_id=str(user_id),
        metadata={"backup_id": backup.id, "settings_count": len(settings)}, ip=ip,
    )
    await db.commit()
    await db.refresh(backup)
    return backup


async def _load_settings(storage_mod, backup: Backup) -> dict:
    if not backup.storage_key:
        return {}
    raw = await storage_mod.get_object(backup.storage_key)
    doc = json.loads(raw)
    return doc.get("settings", {}) if isinstance(doc, dict) else {}


async def diff_backup(
    db: AsyncSession, storage_mod, device: Device, backup: Backup
) -> BackupDiffResponse:
    backup_settings = await _load_settings(storage_mod, backup)
    current = await _current_settings(db, device.id)
    defs = {
        d.key: d
        for d in (await db.execute(select(SettingDefinition))).scalars().all()
    }
    changes: list[BackupDiffEntry] = []
    unchanged = 0
    for key, bval in backup_settings.items():
        cval = current.get(key, defs[key].default_value if key in defs else None)
        if cval != bval:
            changes.append(
                BackupDiffEntry(
                    key=key,
                    label=defs[key].label if key in defs else key,
                    current_value=cval,
                    backup_value=bval,
                )
            )
        else:
            unchanged += 1
    return BackupDiffResponse(
        device_id=device.id, backup_id=backup.id, changes=changes, unchanged=unchanged
    )


async def restore_backup(
    db: AsyncSession,
    storage_mod,
    manager,
    user_id: int,
    device: Device,
    backup: Backup,
    ip: str | None,
) -> int:
    # Safety: a backup can contain driving-affecting settings -> offroad only.
    status_row = await db.get(DeviceStatus, device.id)
    if status_row is not None and status_row.onroad:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device is onroad; restore is only allowed while offroad",
        )
    backup_settings = await _load_settings(storage_mod, backup)
    # Keep only known, remote-configurable settings.
    defs = {
        d.key: d for d in (await db.execute(select(SettingDefinition))).scalars().all()
    }
    to_apply = {
        k: v for k, v in backup_settings.items()
        if k in defs and defs[k].remote_configurable
    }
    command = DeviceCommand(
        device_id=device.id,
        name=CommandName.RESTORE_SETTINGS.value,
        args={"settings": to_apply, "backup_id": backup.id},
        requires_offroad=True,
        created_by=user_id,
        status=CommandStatus.QUEUED,
    )
    db.add(command)
    await db.flush()
    await record_audit(
        db,
        action="device.backup.restore",
        actor_type="user",
        actor_id=str(user_id),
        device_id=device.id,
        metadata={"backup_id": backup.id, "count": len(to_apply), "command_id": command.id},
        ip=ip,
    )
    await db.commit()
    await db.refresh(command)
    await manager.send_to_device(
        device.id,
        {"type": "command", "id": command.id, "name": command.name, "args": command.args},
    )
    return len(to_apply)
