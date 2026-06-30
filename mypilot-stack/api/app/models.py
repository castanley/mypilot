"""SQLAlchemy ORM models for the MyPilot M1/M2 schema.

Types are intentionally portable (generic ``JSON``/``String``/``DateTime``) so the same models
back Postgres in production and SQLite in tests. Status fields are plain strings validated in
the application layer (see the ``*Status`` constants) to avoid DB-enum portability issues.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex


def new_dongle_id() -> str:
    """A comma-style device id: 16 lowercase hex chars."""
    return uuid.uuid4().hex[:16]


# --- Status constants --------------------------------------------------------------------------

class DeviceStatusValue:
    PENDING = "pending_activation"
    ACTIVE = "active"
    REVOKED = "revoked"


class KeyStatus:
    ACTIVE = "active"
    REVOKED = "revoked"


class PairingStatus:
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    EXPIRED = "expired"


class CommandStatus:
    QUEUED = "queued"
    SENT = "sent"
    DONE = "done"
    FAILED = "failed"
    REJECTED = "rejected"


class SettingType:
    BOOLEAN = "boolean"
    NUMBER = "number"
    ENUM = "enum"
    STRING = "string"


class DangerLevel:
    SAFE = "safe"
    CAUTION = "caution"
    DANGEROUS = "dangerous"


class SettingChangeStatus:
    PENDING = "pending"
    APPLIED = "applied"
    FAILED = "failed"
    REJECTED = "rejected"


class UploadStatus:
    UPLOADING = "uploading"
    COMPLETE = "complete"
    FAILED = "failed"


class LogKind:
    CRASH = "crash"
    SYSTEM = "system"
    QLOG = "qlog"
    RLOG = "rlog"


class UpdateState:
    IDLE = "idle"
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    DONE = "done"
    FAILED = "failed"


class SoftwareChannel:
    RELEASE = "release"
    STAGING = "staging"
    NIGHTLY = "nightly"
    MASTER = "master"


class BackupKind:
    SETTINGS = "settings"


# --- Tables ------------------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_dongle_id)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    alias: Mapped[str] = mapped_column(String(128), nullable=False, default="New device")
    hardware_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=DeviceStatusValue.PENDING, nullable=False
    )
    platform: Mapped[str | None] = mapped_column(String(128), nullable=True)
    software_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Device capability vector (e.g. torque_allowed, brand, enable_bsm) used to gate settings.
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    # M5/M7 mirrors of device-reported state (authoritative value lives on DeviceStatus), plus
    # rollback targets captured at switch/update time.
    active_model_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    previous_model_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    update_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    previous_software_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # True for SIMULATED test devices created via the admin dev tools (drive replay, etc.). Real
    # paired devices are always False. Dev-tool mutations filter on this so they can never touch a
    # real device; the UI shows a "SIM" badge.
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    keys: Mapped[list["DeviceKey"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    status_row: Mapped["DeviceStatus | None"] = relationship(
        back_populates="device", cascade="all, delete-orphan", uselist=False
    )


class DeviceKey(Base):
    __tablename__ = "device_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    public_key_b64: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=KeyStatus.ACTIVE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    device: Mapped[Device] = relationship(back_populates="keys")


class DeviceStatus(Base):
    __tablename__ = "device_status"

    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    # Stack-owned presence + receive-time (the authoritative clock).
    online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    onroad: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The whole device-reported telemetry envelope ({captured_at, onroad, subsystems{...}}); see
    # mypilot_protocol.telemetry. One JSON blob instead of a dozen scattered columns — status is
    # disposable live data (re-sent every heartbeat), so it needs no per-field queryability. Fields
    # the device LIST needs (software_version/branch/platform/active_model) are mirrored onto Device.
    telemetry: Mapped[dict] = mapped_column(JSON, default=dict)
    # Accumulating [lat, lon] trail for the CURRENT drive — appended as the device moves while onroad,
    # cleared when it goes offroad. Bounded length. Lets the live map draw a blue polyline that
    # survives a page refresh (seeded from here), not just a client-only trail.
    live_track: Mapped[list | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    device: Mapped[Device] = relationship(back_populates="status_row")


class DevicePairing(Base):
    __tablename__ = "device_pairings"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    hardware_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    public_key_b64: Mapped[str] = mapped_column(String(128), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=PairingStatus.PENDING, nullable=False)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeviceCommand(Base):
    __tablename__ = "device_commands"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default=CommandStatus.QUEUED, nullable=False)
    requires_offroad: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CommandResult(Base):
    __tablename__ = "command_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    command_id: Mapped[str] = mapped_column(
        ForeignKey("device_commands.id", ondelete="CASCADE"), index=True
    )
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)  # user | device | system
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    event_metadata: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class SettingDefinition(Base):
    """Global catalog of settings (the metadata that drives the Settings UI)."""

    __tablename__ = "setting_definitions"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # boolean|number|enum|string
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)  # [{value, label}]
    default_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # typed default
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    step: Mapped[float | None] = mapped_column(Float, nullable=True)
    panel: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    requires_offroad: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_reboot: Mapped[bool] = mapped_column(Boolean, default=False)
    danger_level: Mapped[str] = mapped_column(String(16), default=DangerLevel.SAFE)
    remote_configurable: Mapped[bool] = mapped_column(Boolean, default=True)
    # Capability field that gates visibility (null = always shown).
    capability: Mapped[str | None] = mapped_column(String(48), nullable=True)
    # When true, a remote (web) write may turn this setting OFF or move it between non-off values,
    # but may NOT move it from an "off" state to a non-off one — that "arming" requires the device
    # itself (physical-presence consent). Key-agnostic mechanism; deployments opt specific keys in.
    arm_on_device_only: Mapped[bool] = mapped_column(Boolean, default=False)


class DeviceSetting(Base):
    """Current value of a setting on a specific device (reported by the agent)."""

    __tablename__ = "device_settings"

    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class SettingChange(Base):
    """Audit + lifecycle of a remote setting change request."""

    __tablename__ = "setting_changes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default=SettingChangeStatus.PENDING, nullable=False
    )
    requires_offroad: Mapped[bool] = mapped_column(Boolean, default=False)
    requested_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)  # device route identifier
    alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_state: Mapped[str] = mapped_column(String(16), default="logs")  # metadata|logs|full
    upload_status: Mapped[str] = mapped_column(String(16), default=UploadStatus.UPLOADING)
    parse_status: Mapped[str] = mapped_column(String(16), default="pending")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    start_location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    end_location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # GPS track for the drive map: an ordered polyline [[lat, lon], ...] (5-dp floats, downsampled on
    # the device from the qlog). Privacy-sensitive (plots where the owner drives) — only ever served
    # by the owner-gated per-drive /track endpoint, NEVER in the routes LIST (would bloat + leak).
    # start_lat/start_lon are scalar copies of the first point so the overview map can place a marker
    # without loading the whole track array.
    gps_track: Mapped[list | None] = mapped_column(JSON, nullable=True)
    start_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    files: Mapped[list["RouteFile"]] = relationship(
        back_populates="route", cascade="all, delete-orphan"
    )


class RouteFile(Base):
    __tablename__ = "route_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    route_id: Mapped[str] = mapped_column(ForeignKey("routes.id", ondelete="CASCADE"), index=True)
    segment_index: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(64), nullable=False)  # qlog.zst, rlog.zst, ...
    kind: Mapped[str] = mapped_column(String(16), default="qlog")
    storage_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    route: Mapped[Route] = relationship(back_populates="files")


class Log(Base):
    __tablename__ = "logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    route_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default=LogKind.SYSTEM)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    upload_status: Mapped[str] = mapped_column(String(16), default=UploadStatus.UPLOADING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="route")  # route|log
    target_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # route id
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|complete|failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Model(Base):
    """Global catalog of driving models (artifacts stored in object storage)."""

    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(32), default="")
    generation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    runner: Mapped[str | None] = mapped_column(String(32), nullable=True)  # tinygrad|snpe|...
    build_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), default="")  # sha256 hex of artifact
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    compatible_device_types: Mapped[list] = mapped_column(JSON, default=list)
    compatible_versions: Mapped[list] = mapped_column(JSON, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SoftwareRelease(Base):
    """Global catalog of MyPilot software releases per channel."""

    __tablename__ = "software_releases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default=SoftwareChannel.RELEASE, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    build_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    install_url: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Backup(Base):
    """A settings snapshot (JSON in object storage) used for restore + device migration."""

    __tablename__ = "backups"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    device_id: Mapped[str | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default=BackupKind.SETTINGS)
    storage_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    settings_count: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_alias: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
