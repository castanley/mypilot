"""Settings validation, device sync, change-result handling, and response building."""

from __future__ import annotations

from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .audit import record_audit
from .models import (
    Device,
    DeviceSetting,
    SettingChange,
    SettingChangeStatus,
    SettingDefinition,
    SettingType,
)
from .redis_client import publish_event
from .schemas import SettingOut, SettingsPanel, SettingsResponse, SettingsSection
from .settings_catalog import PANELS


def validate_and_coerce(defn: SettingDefinition, value):
    """Validate ``value`` against the definition; return the coerced value or raise ValueError."""
    t = defn.type
    if t == SettingType.BOOLEAN:
        if isinstance(value, bool):
            return value
        raise ValueError("expected a boolean")
    if t == SettingType.NUMBER:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("expected a number")
        v = float(value)
        if defn.min_value is not None and v < defn.min_value:
            raise ValueError(f"must be >= {defn.min_value}")
        if defn.max_value is not None and v > defn.max_value:
            raise ValueError(f"must be <= {defn.max_value}")
        return value
    if t == SettingType.ENUM:
        if isinstance(value, bool):
            raise ValueError("not a valid option")
        allowed = [o.get("value") for o in (defn.options or [])]
        if value not in allowed:
            raise ValueError("not a valid option")
        return value
    if t == SettingType.STRING:
        if not isinstance(value, str):
            raise ValueError("expected a string")
        if defn.options and value not in [o.get("value") for o in defn.options]:
            raise ValueError("not a valid option")
        return value
    raise ValueError("unknown setting type")


async def apply_settings_sync(
    db: AsyncSession, device: Device, capabilities: dict | None, values: dict | None
) -> None:
    """Persist a device's reported capabilities + current setting values."""
    if isinstance(capabilities, dict):
        device.capabilities = capabilities
    for key, val in (values or {}).items():
        row = await db.get(DeviceSetting, (device.id, key))
        if row is None:
            db.add(DeviceSetting(device_id=device.id, key=key, value=val))
        else:
            row.value = val
    await db.commit()


async def record_setting_result(
    db: AsyncSession, redis: Redis, device: Device, change_id: str, ok: bool, value, detail
) -> SettingChange | None:
    change = await db.get(SettingChange, change_id)
    if change is None or change.device_id != device.id:
        return None
    change.status = SettingChangeStatus.APPLIED if ok else SettingChangeStatus.FAILED
    change.detail = detail
    change.applied_at = datetime.now(timezone.utc)
    if ok:
        final = value if value is not None else change.new_value
        row = await db.get(DeviceSetting, (device.id, change.key))
        if row is None:
            db.add(DeviceSetting(device_id=device.id, key=change.key, value=final))
        else:
            row.value = final
    await record_audit(
        db,
        action="device.setting.result",
        actor_type="device",
        actor_id=device.id,
        device_id=device.id,
        metadata={"key": change.key, "ok": ok, "change_id": change_id},
    )
    await db.commit()
    await publish_event(
        redis,
        {
            "type": "device_event",
            "device_id": device.id,
            "event": "setting_result",
            "key": change.key,
            "ok": ok,
        },
    )
    return change


def is_off_value(value) -> bool:
    """Generic 'off' test for the arm-on-device-only gate: absent, falsey, zero, empty, or the
    literal string 'off' (covers bool/enum/number setting shapes). Shared with the settings router."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("", "off", "false", "0", "none")
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value == 0
    return False


def _to_out(defn: SettingDefinition, current, is_default: bool) -> SettingOut:
    return SettingOut(
        key=defn.key,
        type=defn.type,
        label=defn.label,
        description=defn.description or "",
        options=defn.options,
        default_value=defn.default_value,
        min_value=defn.min_value,
        max_value=defn.max_value,
        step=defn.step,
        panel=defn.panel,
        section=defn.section,
        requires_offroad=defn.requires_offroad,
        requires_reboot=defn.requires_reboot,
        danger_level=defn.danger_level,
        remote_configurable=defn.remote_configurable,
        capability=defn.capability,
        arm_on_device_only=defn.arm_on_device_only,
        current_value=current,
        # Gated (web cannot arm) when the key is arm-on-device-only and currently off.
        gated=bool(defn.arm_on_device_only and is_off_value(current)),
        is_default=is_default,
    )


async def build_settings_response(
    db: AsyncSession, device: Device, onroad: bool
) -> SettingsResponse:
    defs = (
        await db.execute(select(SettingDefinition).order_by(SettingDefinition.order))
    ).scalars().all()
    values = {
        ds.key: ds.value
        for ds in (
            await db.execute(
                select(DeviceSetting).where(DeviceSetting.device_id == device.id)
            )
        ).scalars()
    }
    caps = device.capabilities or {}

    panels_out: list[SettingsPanel] = []
    for p in sorted(PANELS, key=lambda x: x["order"]):
        pdefs = [
            d for d in defs
            if d.panel == p["id"] and (not d.capability or caps.get(d.capability))
        ]
        if not pdefs:
            continue
        sections: dict[str | None, list[SettingOut]] = {}
        order: list[str | None] = []
        for d in pdefs:
            if d.section not in sections:
                sections[d.section] = []
                order.append(d.section)
            has_val = d.key in values
            current = values[d.key] if has_val else d.default_value
            is_default = (not has_val) or values[d.key] == d.default_value
            sections[d.section].append(_to_out(d, current, is_default))
        panels_out.append(
            SettingsPanel(
                id=p["id"], label=p["label"], order=p["order"],
                sections=[SettingsSection(name=s, settings=sections[s]) for s in order],
            )
        )

    synced = bool(values) or bool(caps)
    return SettingsResponse(panels=panels_out, onroad=onroad, synced=synced)
