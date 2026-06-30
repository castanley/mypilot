"""Helper for writing audit events. Every remote action should leave an audit trail."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditEvent


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    actor_type: str,
    actor_id: str | None = None,
    device_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEvent:
    """Insert an audit event. Caller commits (kept in the same transaction as the action).

    Never pass secrets/tokens/keys in ``metadata`` — audit rows are readable in the UI.
    """
    event = AuditEvent(
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        device_id=device_id,
        event_metadata=metadata or {},
        ip=ip,
    )
    session.add(event)
    return event
