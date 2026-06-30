"""Pydantic request/response models (the OpenAPI contract for MyPilot Web + Agent)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    detail: str


# --- Auth --------------------------------------------------------------------------------------

class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class ForkConfig(BaseModel):
    """Deployment/fork config: branding + public Stack URL + GitHub install source."""

    project_name: str = Field(default="MyPilot", max_length=60)
    stack_url: str = Field(max_length=256)
    source_url: str = Field(default="", max_length=256)
    installer_base: str = Field(max_length=256)
    github_owner: str = Field(max_length=100)
    release_branch: str = Field(max_length=100)
    staging_branch: str = Field(max_length=100)
    # Derived, read-only previews of the resulting install URLs.
    release_install_url: str | None = None
    staging_install_url: str | None = None


class ForkConfigUpdate(BaseModel):
    project_name: str | None = Field(default=None, max_length=60)
    stack_url: str | None = Field(default=None, max_length=256)
    source_url: str | None = Field(default=None, max_length=256)
    installer_base: str | None = Field(default=None, max_length=256)
    github_owner: str | None = Field(default=None, max_length=100)
    release_branch: str | None = Field(default=None, max_length=100)
    staging_branch: str | None = Field(default=None, max_length=100)


class PublicSite(BaseModel):
    """Non-sensitive site branding for the public landing page."""

    project_name: str = "MyPilot"
    stack_url: str = ""
    source_url: str = ""


class Me(BaseModel):
    id: int
    username: str
    is_admin: bool
    csrf_token: str


class SetupState(BaseModel):
    needs_setup: bool


# --- Devices -----------------------------------------------------------------------------------

# --- Telemetry envelope (schema v2) — see mypilot_protocol.telemetry for the contract -----------
# Modular subsystems, units in keys, enums normalized to closed sets. Every field Optional: an absent
# subsystem means the device lacks it; a present null field means the sensor reported nothing.

class ThermalTelemetry(BaseModel):
    status: str | None = None      # green|yellow|red
    max_c: float | None = None     # hottest component °C (single source of truth)
    cpu_c: float | None = None
    gpu_c: float | None = None
    memory_c: float | None = None
    ambient_c: float | None = None


class StorageTelemetry(BaseModel):
    used_pct: float | None = None
    total_bytes: int | None = None
    used_bytes: int | None = None
    free_bytes: int | None = None


class StatusOnly(BaseModel):
    status: str | None = None      # gps: has_fix|searching|no_signal|error ; panda: connected|available|disconnected


class DrivingTelemetry(BaseModel):
    """Live motion while onroad. Every field nullable: GPS warms up ~20-30s (position null early),
    heading is null below a noise-floor speed, and all are null off-device/offroad. Distinct from
    `gps` (fix-status) — do NOT fold into the shared StatusOnly. Position is privacy-sensitive; the
    realtime fan-out must be owner-scoped before it streams (see realtime manager)."""
    speed_ms: float | None = None       # vehicle speed, m/s (carState.vEgo; GPS Doppler fallback)
    heading_deg: float | None = None    # travel direction 0-360, from GPS bearing
    latitude: float | None = None       # bare coordinate (identifier-like, no unit suffix)
    longitude: float | None = None
    accuracy_m: float | None = None     # horizontal position accuracy, meters
    gear: str | None = None             # PRNDL: park|drive|reverse|neutral|... (carState.gearShifter)


class PowerTelemetry(BaseModel):
    uptime_s: int | None = None


class PlatformTelemetry(BaseModel):
    name: str | None = None        # e.g. "Chrysler Ram Hd"
    device_type: str | None = None


class SoftwareTelemetry(BaseModel):
    version: str | None = None
    branch: str | None = None
    update_channel: str | None = None
    update_state: str | None = None   # idle|downloading|installing|done|failed
    target_version: str | None = None


class ModelsTelemetry(BaseModel):
    active_ref: str | None = None
    installed_refs: list[str] = Field(default_factory=list)
    available: list[dict] = Field(default_factory=list)


class Subsystems(BaseModel):
    thermal: ThermalTelemetry | None = None
    storage: StorageTelemetry | None = None
    gps: StatusOnly | None = None
    driving: DrivingTelemetry | None = None
    panda: StatusOnly | None = None
    power: PowerTelemetry | None = None
    platform: PlatformTelemetry | None = None
    software: SoftwareTelemetry | None = None
    models: ModelsTelemetry | None = None


class DeviceStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # Presence + receive-time are stack-owned (the authoritative clock).
    online: bool = False
    onroad: bool = False
    last_heartbeat_at: datetime | None = None
    updated_at: datetime | None = None
    # The telemetry envelope reported by the device.
    captured_at: datetime | None = None   # advisory device sample time
    subsystems: Subsystems | None = None
    # True while an admin drive-replay is feeding a simulated device (both clients show a badge).
    replaying: bool = False
    # Accumulating [lat, lon] trail for the current drive — the live map's blue polyline.
    live_track: list[list[float]] = Field(default_factory=list)


class DeviceSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    alias: str
    status: str
    platform: str | None = None
    software_version: str | None = None
    branch: str | None = None
    created_at: datetime
    # True for admin-created SIM test devices (drive replay etc.) — the UI shows a "SIM" badge. It's
    # a real field surfaced to every client, never web-local. Real devices are always false.
    is_simulated: bool = False
    # Derived/joined fields:
    online: bool = False
    onroad: bool = False
    last_heartbeat_at: datetime | None = None


class DeviceDetail(DeviceSummary):
    hardware_id: str | None = None
    activated_at: datetime | None = None
    status_detail: DeviceStatusOut | None = None


class DeviceUpdate(BaseModel):
    alias: str = Field(min_length=1, max_length=128)


class CommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    name: str
    status: str
    requires_offroad: bool
    created_at: datetime
    completed_at: datetime | None = None


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_type: str
    actor_id: str | None = None
    action: str
    device_id: str | None = None
    event_metadata: dict = Field(default_factory=dict)
    created_at: datetime


# --- Pairing -----------------------------------------------------------------------------------

class RegisterStartRequest(BaseModel):
    hardware_id: str | None = Field(default=None, max_length=128)
    public_key: str = Field(max_length=128, description="base64 Ed25519 public key")
    hostname: str | None = Field(default=None, max_length=128)


class RegisterStartResponse(BaseModel):
    pairing_id: str
    code: str
    expires_at: datetime
    poll_interval: int


class ClaimRequest(BaseModel):
    code: str = Field(min_length=4, max_length=32)
    alias: str | None = Field(default=None, max_length=128)


class ClaimResponse(BaseModel):
    device: DeviceSummary


class RegisterCompleteRequest(BaseModel):
    pairing_id: str = Field(max_length=32)
    signature: str = Field(max_length=128, description="base64 Ed25519 signature of the challenge")


class DeviceConfig(BaseModel):
    heartbeat_interval: int
    presence_ttl: int


class RegisterCompleteResponse(BaseModel):
    status: str  # "pending" until claimed, then "active"
    device_id: str | None = None
    config: DeviceConfig | None = None


# --- Device self-reporting (signed) ------------------------------------------------------------

class HeartbeatRequest(BaseModel):
    """The telemetry envelope the device posts/streams. See mypilot_protocol.telemetry. The body IS
    the envelope — no legacy flat fields, no version field."""
    captured_at: datetime | None = None
    onroad: bool = False
    subsystems: Subsystems = Field(default_factory=Subsystems)


class CommandResultRequest(BaseModel):
    ok: bool
    detail: str | None = Field(default=None, max_length=2000)


class SettingsSyncRequest(BaseModel):
    capabilities: dict = Field(default_factory=dict)
    values: dict = Field(default_factory=dict)


class SettingResultRequest(BaseModel):
    change_id: str = Field(max_length=32)
    key: str = Field(max_length=64)
    ok: bool
    value: Any = None
    detail: str | None = Field(default=None, max_length=2000)


# --- Routes & logs (M4) ------------------------------------------------------------------------

class RouteFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    segment_index: int
    name: str
    kind: str
    size_bytes: int
    uploaded: bool


class RouteSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    name: str
    alias: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_s: int | None = None
    distance_m: float | None = None
    segment_count: int = 0
    is_public: bool = False
    privacy_state: str = "logs"
    upload_status: str = "uploading"
    parse_status: str = "pending"
    size_bytes: int = 0
    # Scalar start point for the overview map marker. The FULL track is deliberately NOT here — it
    # would bloat the list response; fetch it per-drive from /routes/{id}/track.
    start_lat: float | None = None
    start_lon: float | None = None
    has_track: bool = False
    created_at: datetime


class RouteDetail(RouteSummary):
    start_location: str | None = None
    end_location: str | None = None
    files: list[RouteFileOut] = Field(default_factory=list)


class RouteTrackOut(BaseModel):
    """The full GPS polyline for one drive (owner-gated, lazy-loaded by the map)."""
    route_id: str
    track: list[list[float]] = Field(default_factory=list)


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    route_name: str | None = None
    kind: str
    name: str
    size_bytes: int = 0
    upload_status: str = "uploading"
    created_at: datetime


class RouteFileDecl(BaseModel):
    segment_index: int = 0
    name: str = Field(max_length=64)
    kind: str = Field(default="qlog", max_length=16)


class RouteStartRequest(BaseModel):
    name: str = Field(max_length=128)
    alias: str | None = Field(default=None, max_length=128)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_s: int | None = None
    distance_m: float | None = None
    segment_count: int = 0
    privacy_state: str = Field(default="logs", max_length=16)
    start_location: str | None = Field(default=None, max_length=128)
    end_location: str | None = Field(default=None, max_length=128)
    # Optional GPS polyline extracted on-device from the qlog: ordered [[lat, lon], ...]. Capped to
    # keep the metadata POST small; the device already downsamples to ~1 pt/sec + dedupes when stopped.
    track: list[list[float]] | None = Field(default=None, max_length=20000)
    files: list[RouteFileDecl] = Field(default_factory=list)


class RouteStartResponse(BaseModel):
    upload_id: str
    route_id: str
    # Number of points in the track the server is now storing for this route. The device compares
    # this to what it sent: it only marks the track as delivered once the stored count matches, so a
    # partial track that lost the grow-only race is retried (not silently considered done).
    track_points: int = 0


class LogStartRequest(BaseModel):
    kind: str = Field(default="system", max_length=16)
    name: str = Field(max_length=128)
    route_name: str | None = Field(default=None, max_length=128)


class RetentionConfig(BaseModel):
    # Per-category retention in days (0 = keep forever). `days` is the legacy single knob, kept for
    # back-compat: when route_days/log_days are omitted it applies to both.
    days: int = Field(default=0, ge=0, le=3650)
    route_days: int | None = Field(default=None, ge=0, le=3650)
    log_days: int | None = Field(default=None, ge=0, le=3650)

    def resolved(self) -> tuple[int, int]:
        """(route_days, log_days) — explicit per-category values win, else fall back to `days`."""
        return (
            self.route_days if self.route_days is not None else self.days,
            self.log_days if self.log_days is not None else self.days,
        )


class RetentionRunResult(BaseModel):
    routes_deleted: int
    logs_deleted: int
    route_days: int
    log_days: int


class StorageReconcileResult(BaseModel):
    route_files_reconciled: int
    logs_reconciled: int


class RouteDeleteAllResult(BaseModel):
    routes_deleted: int


# --- Models (M5) -------------------------------------------------------------------------------

class ModelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    key: str
    name: str
    description: str = ""
    version: str = ""
    generation: str | None = None
    runner: str | None = None
    build_time: datetime | None = None
    checksum: str = ""
    size_bytes: int = 0
    compatible_device_types: list[str] = Field(default_factory=list)
    compatible_versions: list[str] = Field(default_factory=list)
    is_default: bool = False
    created_at: datetime


class DeviceModelView(ModelOut):
    active: bool = False
    installed: bool = False
    compatible: bool = True


class DeviceModelsResponse(BaseModel):
    active_model_key: str | None = None
    onroad: bool = False
    models: list[DeviceModelView] = Field(default_factory=list)


class ModelSwitchRequest(BaseModel):
    model_key: str = Field(max_length=64)
    confirm: bool = False


# --- Software (M7) -----------------------------------------------------------------------------

class SoftwareReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: str
    channel: str
    notes: str = ""
    build_time: datetime | None = None
    install_url: str | None = None
    is_current: bool = False
    created_at: datetime


class DeviceSoftwareState(BaseModel):
    current_version: str | None = None
    current_branch: str | None = None
    update_channel: str | None = None
    update_state: str | None = None
    target_version: str | None = None
    previous_version: str | None = None
    onroad: bool = False
    releases: list[SoftwareReleaseOut] = Field(default_factory=list)


class SoftwareUpdateRequest(BaseModel):
    version: str = Field(max_length=64)
    confirm: bool = False


# --- Backups (M6) ------------------------------------------------------------------------------

class BackupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str | None = None
    name: str
    kind: str = "settings"
    size_bytes: int = 0
    checksum: str = ""
    settings_count: int = 0
    note: str | None = None
    source_alias: str | None = None
    created_at: datetime


class BackupCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=500)


class BackupRestoreRequest(BaseModel):
    confirm: bool = False


class BackupDiffEntry(BaseModel):
    key: str
    label: str
    current_value: Any = None
    backup_value: Any = None


class BackupDiffResponse(BaseModel):
    device_id: str
    backup_id: str
    changes: list[BackupDiffEntry] = Field(default_factory=list)
    unchanged: int = 0


# --- Health ------------------------------------------------------------------------------------

class HealthComponent(BaseModel):
    ok: bool
    detail: str | None = None
    # Optional usage stats (object_storage reports {used_bytes, object_count}).
    usage: dict | None = None


class HealthResponse(BaseModel):
    ok: bool
    components: dict[str, HealthComponent]


# --- Settings (M3) -----------------------------------------------------------------------------

class SettingOut(BaseModel):
    key: str
    type: str
    label: str
    description: str = ""
    options: list[dict] | None = None
    default_value: Any = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    panel: str
    section: str | None = None
    requires_offroad: bool = False
    requires_reboot: bool = False
    danger_level: str = "safe"
    remote_configurable: bool = True
    capability: str | None = None
    arm_on_device_only: bool = False
    current_value: Any = None
    is_default: bool = True
    # True when arm_on_device_only is set AND the device's current value is off: the web may not
    # arm it (must be enabled on the device). Lets the UI disable the control with an explanation.
    gated: bool = False


class SettingsSection(BaseModel):
    name: str | None = None
    settings: list[SettingOut]


class SettingsPanel(BaseModel):
    id: str
    label: str
    order: int
    sections: list[SettingsSection]


class SettingsResponse(BaseModel):
    panels: list[SettingsPanel]
    onroad: bool
    synced: bool  # whether the device has reported its settings/capabilities yet


class SettingChangeRequest(BaseModel):
    # The setting key now lives in the path (POST /settings/{key}/change), matching the reset sibling;
    # the body carries only the new value + confirmation.
    value: Any
    confirm: bool = False


class SettingChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    key: str
    old_value: Any = None
    new_value: Any = None
    status: str
    requires_offroad: bool
    detail: str | None = None
    created_at: datetime
    applied_at: datetime | None = None
