"""Device ownership — the one place "may this user touch this device" is decided.

A device belongs to the user whose `owner_id` it carries. The device routers (devices, routes,
settings, backups, software) all call through here rather than inlining the check, so the rule lives in
exactly one place and the cross-cutting test in tests/test_owner_scoping.py can pin it. Referenced as
`ownership.owns_device(...)` (module-qualified) so the check has a single mockable home. The `db`
session is accepted (and currently unused) so the predicate keeps a stable signature if it ever needs
to read from the database, without touching every call site.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from .models import Device, User


async def owns_device(user: User, device: Device | None, db: AsyncSession | None = None) -> bool:
    """True iff `user` owns `device`. A None device returns False so callers can fold the existence
    check into the ownership check."""
    return device is not None and device.owner_id == user.id


def device_owner_filter(user: User) -> ColumnElement[bool]:
    """A SQLAlchemy WHERE clause scoping a Device query to the devices `user` owns (for list endpoints)."""
    return Device.owner_id == user.id
