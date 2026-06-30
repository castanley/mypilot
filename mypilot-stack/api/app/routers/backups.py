"""Settings backups: create (snapshot), list, download JSON, diff, restore, import, delete (M6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import backups_service, ownership, storage
from ..audit import record_audit
from ..db import get_session
from ..deps import CurrentAuth, client_ip, get_current_user, require_csrf
from ..models import Backup, Device, DeviceStatusValue, User
from ..schemas import (
    BackupCreateRequest,
    BackupDiffResponse,
    BackupOut,
    BackupRestoreRequest,
    Message,
)

router = APIRouter(prefix="/api", tags=["backups"])

MAX_BACKUP_BYTES = 5 * 1024 * 1024


async def _owned_device(db: AsyncSession, user: User, device_id: str) -> Device:
    device = await db.get(Device, device_id)
    if not await ownership.owns_device(user, device, db):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


async def _owned_backup(db: AsyncSession, user: User, backup_id: str) -> Backup:
    backup = await db.get(Backup, backup_id)
    if backup is None or backup.created_by != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    return backup


@router.get("/backups", response_model=list[BackupOut])
async def list_backups(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
    device_id: str | None = None,
) -> list[BackupOut]:
    stmt = select(Backup).where(Backup.created_by == user.id)
    if device_id:
        stmt = stmt.where(Backup.device_id == device_id)
    stmt = stmt.order_by(Backup.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [BackupOut.model_validate(b) for b in rows]


@router.post(
    "/devices/{device_id}/backups", response_model=BackupOut, status_code=status.HTTP_201_CREATED
)
async def create_backup(
    device_id: str,
    payload: BackupCreateRequest,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> BackupOut:
    device = await _owned_device(db, auth.user, device_id)
    backup = await backups_service.create_backup(
        db, storage, auth.user.id, device, payload.name, payload.note, client_ip(request)
    )
    return BackupOut.model_validate(backup)


@router.post("/backups/import", response_model=BackupOut, status_code=status.HTTP_201_CREATED)
async def import_backup(
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> BackupOut:
    raw = await request.body()
    if len(raw) > MAX_BACKUP_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Too large")
    backup = await backups_service.create_from_upload(
        db, storage, auth.user.id, raw, client_ip(request)
    )
    return BackupOut.model_validate(backup)


@router.get("/backups/{backup_id}", response_model=BackupOut)
async def get_backup(
    backup_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> BackupOut:
    return BackupOut.model_validate(await _owned_backup(db, user, backup_id))


@router.get("/backups/{backup_id}/download")
async def download_backup(
    backup_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> Response:
    backup = await _owned_backup(db, user, backup_id)
    if not backup.storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup has no data")
    data = await storage.get_object(backup.storage_key)
    fname = f"{backup.name.replace(' ', '_')}.json"
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": storage.content_disposition(fname)},
    )


@router.delete("/backups/{backup_id}", response_model=Message)
async def delete_backup(
    backup_id: str,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Message:
    backup = await _owned_backup(db, auth.user, backup_id)
    if backup.storage_key:
        try:
            await storage.delete_object(backup.storage_key)
        except Exception:  # noqa: BLE001
            pass
    await record_audit(
        db, action="backup.delete", actor_type="user", actor_id=str(auth.user.id),
        device_id=backup.device_id, metadata={"backup_id": backup_id}, ip=client_ip(request),
    )
    await db.delete(backup)
    await db.commit()
    return Message(detail="Backup deleted")


@router.get("/devices/{device_id}/backups/{backup_id}/diff", response_model=BackupDiffResponse)
async def diff_backup(
    device_id: str,
    backup_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> BackupDiffResponse:
    device = await _owned_device(db, user, device_id)
    backup = await _owned_backup(db, user, backup_id)
    return await backups_service.diff_backup(db, storage, device, backup)


@router.post("/devices/{device_id}/backups/{backup_id}/restore", response_model=Message)
async def restore_backup(
    device_id: str,
    backup_id: str,
    payload: BackupRestoreRequest,
    request: Request,
    auth: CurrentAuth = Depends(require_csrf),
    db: AsyncSession = Depends(get_session),
) -> Message:
    device = await _owned_device(db, auth.user, device_id)
    if device.status != DeviceStatusValue.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Device is not active")
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Restore requires confirmation"
        )
    backup = await _owned_backup(db, auth.user, backup_id)
    count = await backups_service.restore_backup(
        db, storage, request.app.state.manager, auth.user.id, device, backup, client_ip(request)
    )
    return Message(detail=f"Restoring {count} settings to {device.alias}")
