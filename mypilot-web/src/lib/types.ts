// Data contracts — these mirror the MyPilot REST/WS API exactly.
// Do not change these shapes; the UI is designed against them.

export interface Me {
  id: number;
  username: string;
  is_admin: boolean;
  csrf_token: string;
}

export interface HealthResponse {
  ok: boolean;
  components: Record<
    string,
    { ok: boolean; detail: string | null; usage?: Record<string, number> | null }
  >;
  // keys: database, redis, object_storage
}

export interface DeviceSummary {
  id: string;
  alias: string;
  status: string;
  platform: string | null;
  software_version: string | null;
  branch: string | null;
  created_at: string;
  is_simulated: boolean;
  online: boolean;
  onroad: boolean;
  last_heartbeat_at: string | null;
}

// Telemetry envelope — see mypilot_protocol/telemetry.py. Modular subsystems, units in keys.
export interface Subsystems {
  thermal?: {
    status?: string | null;
    max_c?: number | null;
    cpu_c?: number | null;
    gpu_c?: number | null;
    memory_c?: number | null;
    ambient_c?: number | null;
  } | null;
  storage?: { used_pct?: number | null; total_bytes?: number | null; used_bytes?: number | null; free_bytes?: number | null } | null;
  gps?: { status?: string | null } | null;
  // Live motion while onroad (every field nullable: GPS warmup, heading null when slow, all null
  // offroad/off-device). speed_ms in m/s; heading_deg 0-360; latitude/longitude bare coords.
  driving?: {
    speed_ms?: number | null;
    heading_deg?: number | null;
    latitude?: number | null;
    longitude?: number | null;
    accuracy_m?: number | null;
    gear?: string | null; // PRNDL: park|drive|reverse|neutral|...
  } | null;
  panda?: { status?: string | null } | null;
  power?: { uptime_s?: number | null } | null;
  platform?: { name?: string | null; device_type?: string | null } | null;
  software?: {
    version?: string | null;
    branch?: string | null;
    update_channel?: string | null;
    update_state?: string | null;
    target_version?: string | null;
  } | null;
  models?: { active_ref?: string | null; installed_refs?: string[]; available?: unknown[] } | null;
}

export interface DeviceStatusOut {
  online: boolean;
  onroad: boolean;
  last_heartbeat_at: string | null;
  updated_at: string | null;
  captured_at: string | null;
  subsystems: Subsystems | null;
  replaying?: boolean; // admin drive-replay feeding a sim device
  live_track?: [number, number][]; // accumulating [lat,lon] trail for the current drive
}

export interface DeviceDetail extends DeviceSummary {
  hardware_id: string | null;
  activated_at: string | null;
  status_detail: DeviceStatusOut | null;
}

export interface AuditEventOut {
  id: number;
  actor_type: string;
  actor_id: string | null;
  action: string;
  device_id: string | null;
  event_metadata: Record<string, unknown>;
  created_at: string;
}

// ----- Settings -----
export interface SettingOption {
  value: unknown;
  label: string;
}

export type SettingType = "boolean" | "number" | "enum" | "string";
export type DangerLevel = "safe" | "caution" | "dangerous";

export interface SettingOut {
  key: string;
  type: SettingType;
  label: string;
  description: string;
  options: SettingOption[] | null;
  default_value: unknown;
  min_value: number | null;
  max_value: number | null;
  step: number | null;
  panel: string;
  section: string | null;
  requires_offroad: boolean;
  requires_reboot: boolean;
  danger_level: DangerLevel;
  remote_configurable: boolean;
  capability: string | null;
  arm_on_device_only?: boolean;
  current_value: unknown;
  is_default: boolean;
  gated?: boolean;
}

export interface SettingsPanel {
  id: string;
  label: string;
  order: number;
  sections: { name: string | null; settings: SettingOut[] }[];
}

export interface SettingsResponse {
  panels: SettingsPanel[];
  onroad: boolean;
  synced: boolean; // synced=false -> "waiting for device" state
}

// ----- Routes & logs (M4) -----
export interface RouteFileOut {
  id: string;
  segment_index: number;
  name: string;
  kind: string;
  size_bytes: number;
  uploaded: boolean;
}

export interface RouteSummary {
  id: string;
  device_id: string;
  name: string;
  alias: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_s: number | null;
  distance_m: number | null;
  segment_count: number;
  is_public: boolean;
  privacy_state: string;
  upload_status: string;
  parse_status: string;
  size_bytes: number;
  start_lat: number | null;
  start_lon: number | null;
  has_track: boolean;
  created_at: string;
}

export interface RouteDetail extends RouteSummary {
  start_location: string | null;
  end_location: string | null;
  files: RouteFileOut[];
}

// [t, lat, lon] — t = seconds since drive start (aligns with video playback time).
export type TrackPoint = [number, number, number];

export interface RouteTrackOut {
  route_id: string;
  track: TrackPoint[];
}

export interface LogOut {
  id: string;
  device_id: string;
  route_name: string | null;
  kind: string;
  name: string;
  size_bytes: number;
  upload_status: string;
  created_at: string;
}

export interface RetentionConfig {
  days: number;
  route_days?: number | null;
  log_days?: number | null;
}

export interface RetentionRunResult {
  routes_deleted: number;
  logs_deleted: number;
  route_days: number;
  log_days: number;
}

export interface RouteDeleteAllResult {
  routes_deleted: number;
}

// ----- Deployment / fork config -----
export interface ForkConfig {
  project_name: string;
  stack_url: string;
  source_url: string;
  installer_base: string;
  github_owner: string;
  release_branch: string;
  staging_branch: string;
  release_install_url: string | null;
  staging_install_url: string | null;
}

// ----- Models (M5) -----
export interface ModelOut {
  id: string;
  key: string;
  name: string;
  description: string;
  version: string;
  generation: string | null;
  runner: string | null;
  build_time: string | null;
  checksum: string;
  size_bytes: number;
  compatible_device_types: string[];
  compatible_versions: string[];
  is_default: boolean;
  created_at: string;
}

export interface DeviceModelView extends ModelOut {
  active: boolean;
  installed: boolean;
  compatible: boolean;
}

export interface DeviceModelsResponse {
  active_model_key: string | null;
  onroad: boolean;
  models: DeviceModelView[];
}

export interface CommandOut {
  id: string;
  device_id: string;
  name: string;
  status: string;
  requires_offroad: boolean;
  created_at: string;
  completed_at: string | null;
}

// ----- Software (M7) -----
export interface SoftwareReleaseOut {
  id: string;
  version: string;
  channel: string;
  notes: string;
  build_time: string | null;
  install_url: string | null;
  is_current: boolean;
  created_at: string;
}

export interface DeviceSoftwareState {
  current_version: string | null;
  current_branch: string | null;
  update_channel: string | null;
  update_state: string | null;
  target_version: string | null;
  previous_version: string | null;
  onroad: boolean;
  releases: SoftwareReleaseOut[];
}

// ----- Backups (M6) -----
export interface BackupOut {
  id: string;
  device_id: string | null;
  name: string;
  kind: string;
  size_bytes: number;
  checksum: string;
  settings_count: number;
  note: string | null;
  source_alias: string | null;
  created_at: string;
}

export interface BackupDiffEntry {
  key: string;
  label: string;
  current_value: unknown;
  backup_value: unknown;
}

export interface BackupDiffResponse {
  device_id: string;
  backup_id: string;
  changes: BackupDiffEntry[];
  unchanged: number;
}

// ----- Realtime (WS /api/realtime/web) -----
export type RealtimeEvent =
  | { type: "presence"; device_id: string; online: boolean }
  | { type: "device_status"; device_id: string; status: Partial<DeviceStatusOut> }
  | { type: "device_event"; device_id: string; event: string; [k: string]: unknown };

// ----- Setting change lifecycle -----
export type ChangeState = "pending" | "applied" | "failed";

// PATCH /devices/:id/settings and the reset endpoint return this async change record;
// the device applies it and the confirmed value arrives via realtime (setting_result).
export interface SettingChangeOut {
  id: string;
  device_id: string;
  key: string;
  old_value: unknown;
  new_value: unknown;
  status: "pending" | "applied" | "failed" | "rejected";
  requires_offroad: boolean;
  detail: string | null;
  created_at: string;
  applied_at: string | null;
}

// A registered admin utility, surfaced by GET /api/admin/tools and rendered on the Admin hub.
export interface AdminTool {
  key: string;
  label: string;
  href: string;
  description: string;
  icon: string;
}
