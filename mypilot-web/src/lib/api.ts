// Typed client for the MyPilot API. Every call hits the real same-origin /api endpoints;
// mutations attach the CSRF token from the readable `mypilot_csrf` cookie.

import { browser } from "$app/environment";
import type {
  AuditEventOut,
  BackupDiffResponse,
  BackupOut,
  CommandOut,
  DeviceDetail,
  DeviceModelsResponse,
  DeviceSoftwareState,
  DeviceSummary,
  HealthResponse,
  LogOut,
  Me,
  ModelOut,
  RetentionConfig,
  RetentionRunResult,
  RouteDeleteAllResult,
  RouteDetail,
  RouteSummary,
  RouteTrackOut,
  SettingChangeOut,
  SettingsResponse,
} from "$lib/types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

function csrfCookie(): string {
  if (!browser) return "";
  const m = document.cookie.match(/(?:^|;\s*)mypilot_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET") {
    headers.set("X-CSRF-Token", csrfCookie());
    if (init.body) headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`/api${path}`, { ...init, method, headers, credentials: "same-origin" });
  if (!res.ok) {
    let msg: unknown = res.statusText;
    try {
      const data = await res.json();
      msg = data?.detail ?? data?.error ?? msg;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// --- Auth -------------------------------------------------------------------------------------
export const getMe = () => req<Me>("/me");
export const setupState = () => req<{ needs_setup: boolean }>("/auth/setup-state");
export const login = (username: string, password: string) =>
  req<Me>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
export const setup = (username: string, password: string) =>
  req<Me>("/auth/setup", { method: "POST", body: JSON.stringify({ username, password }) });
export const logout = () => req<void>("/auth/logout", { method: "POST" });
export const changePassword = (current_password: string, new_password: string) =>
  req<{ detail: string }>("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password, new_password }),
  });

// --- Deployment / fork config -----------------------------------------------------------------
export const getAdminConfig = () => req<import("$lib/types").ForkConfig>("/admin/config");
export const updateAdminConfig = (patch: Partial<import("$lib/types").ForkConfig>) =>
  req<import("$lib/types").ForkConfig>("/admin/config", {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

// --- Health / audit ---------------------------------------------------------------------------
export const getHealth = () => req<HealthResponse>("/health");
export const getAudit = (deviceId?: string) =>
  req<AuditEventOut[]>(deviceId ? `/devices/${deviceId}/audit` : "/admin/audit");

// --- Devices ----------------------------------------------------------------------------------
export const getDevices = () => req<DeviceSummary[]>("/devices");
export const getDevice = (id: string) => req<DeviceDetail>(`/devices/${id}`);
export async function updateAlias(id: string, alias: string): Promise<DeviceDetail> {
  await req(`/devices/${id}`, { method: "PATCH", body: JSON.stringify({ alias }) });
  return req<DeviceDetail>(`/devices/${id}`);
}
export const rebootDevice = (id: string) => req<void>(`/devices/${id}/reboot`, { method: "POST" });
export const unpairDevice = (id: string) => req<void>(`/devices/${id}`, { method: "DELETE" });
export async function claimDevice(code: string): Promise<DeviceSummary> {
  const res = await req<{ device: DeviceSummary }>("/devices/claim", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
  return res.device;
}

// --- Settings ---------------------------------------------------------------------------------
// NOTE: changes are asynchronous. changeSetting/resetSetting return a *pending* change record;
// the device applies it and the confirmed value lands via realtime (refetch getSettings to reconcile).
export const getSettings = (id: string) => req<SettingsResponse>(`/devices/${id}/settings`);
export const changeSetting = (id: string, key: string, value: unknown, confirm = false) =>
  req<SettingChangeOut>(`/devices/${id}/settings/${key}/change`, {
    method: "POST",
    body: JSON.stringify({ value, confirm }),
  });
export const resetSetting = (id: string, key: string) =>
  req<SettingChangeOut>(`/devices/${id}/settings/${key}/reset`, { method: "POST" });

// --- Routes & logs (M4) -----------------------------------------------------------------------
// Downloads are plain same-origin GETs (cookie-authenticated); use the URL in an <a download>.
export const getRoutes = (deviceId: string) => req<RouteSummary[]>(`/devices/${deviceId}/routes`);
export const getRoute = (routeId: string) => req<RouteDetail>(`/routes/${routeId}`);
export const deleteRoute = (routeId: string) => req<void>(`/routes/${routeId}`, { method: "DELETE" });
export const deleteAllRoutes = (deviceId?: string) =>
  req<RouteDeleteAllResult>(`/routes${deviceId ? `?device_id=${encodeURIComponent(deviceId)}` : ""}`, {
    method: "DELETE",
  });
export const routeFileDownloadUrl = (routeId: string, fileId: string) =>
  `/api/routes/${routeId}/files/${fileId}/download`;
// HLS manifest stitching a drive's qcamera segments; hls.js / Safari play it with scrub/FF.
export const routePlaylistUrl = (routeId: string) => `/api/routes/${routeId}/playlist.m3u8`;
// Inline, Range-capable per-file video stream (used by the player + the manifest's segments).
export const routeFileStreamUrl = (routeId: string, fileId: string) =>
  `/api/routes/${routeId}/files/${fileId}/stream`;

// All the caller's routes across devices (global collection), with optional filters. The drive-map
// overview uses ?has_track=true; the full polyline for a drive is fetched lazily via getRouteTrack.
export const getAllRoutes = (opts?: { deviceId?: string; hasTrack?: boolean }) => {
  const q = new URLSearchParams();
  if (opts?.deviceId) q.set("device_id", opts.deviceId);
  if (opts?.hasTrack) q.set("has_track", "true");
  const qs = q.toString();
  return req<RouteSummary[]>(`/routes${qs ? `?${qs}` : ""}`);
};
// Per-drive GPS polyline (lazy — the heavy array, only when a map is viewed).
export const getRouteTrack = (routeId: string) => req<RouteTrackOut>(`/routes/${routeId}/track`);

export const getLogs = (deviceId: string, kind?: string) =>
  req<LogOut[]>(`/devices/${deviceId}/logs${kind ? `?kind=${encodeURIComponent(kind)}` : ""}`);
export const deleteLog = (logId: string) => req<void>(`/logs/${logId}`, { method: "DELETE" });
export const logDownloadUrl = (logId: string) => `/api/logs/${logId}/download`;

export const getRetention = () => req<RetentionConfig>("/retention");
export const setRetention = (cfg: { route_days: number; log_days: number }) =>
  req<RetentionConfig>("/retention", { method: "PUT", body: JSON.stringify(cfg) });
export const runRetention = () => req<RetentionRunResult>("/retention/run", { method: "POST" });

// --- Models (M5) ------------------------------------------------------------------------------
export const getModels = () => req<ModelOut[]>("/models");
export const getDeviceModels = (id: string) => req<DeviceModelsResponse>(`/devices/${id}/models`);
export const switchModel = (id: string, modelKey: string, confirm = false) =>
  req<CommandOut>(`/devices/${id}/models/switch`, {
    method: "POST",
    body: JSON.stringify({ model_key: modelKey, confirm }),
  });
export const rollbackModel = (id: string) =>
  req<CommandOut>(`/devices/${id}/models/rollback`, { method: "POST" });

// --- Software (M7) ----------------------------------------------------------------------------
export const getReleases = () => req<import("$lib/types").SoftwareReleaseOut[]>("/software/releases");
export const getDeviceSoftware = (id: string) => req<DeviceSoftwareState>(`/devices/${id}/software`);
export const updateSoftware = (id: string, version: string, confirm = false) =>
  req<CommandOut>(`/devices/${id}/software/update`, {
    method: "POST",
    body: JSON.stringify({ version, confirm }),
  });
export const rollbackSoftware = (id: string) =>
  req<CommandOut>(`/devices/${id}/software/rollback`, { method: "POST" });

// --- Backups (M6) -----------------------------------------------------------------------------
export const getBackups = (deviceId?: string) =>
  req<BackupOut[]>(deviceId ? `/backups?device_id=${deviceId}` : "/backups");
export const createBackup = (deviceId: string, name?: string, note?: string) =>
  req<BackupOut>(`/devices/${deviceId}/backups`, {
    method: "POST",
    body: JSON.stringify({ name, note }),
  });
export const deleteBackup = (id: string) => req<void>(`/backups/${id}`, { method: "DELETE" });
export const importBackup = (json: string) =>
  req<BackupOut>("/backups/import", { method: "POST", body: json });
export const backupDownloadUrl = (id: string) => `/api/backups/${id}/download`;
export const diffBackup = (deviceId: string, backupId: string) =>
  req<BackupDiffResponse>(`/devices/${deviceId}/backups/${backupId}/diff`);
export const restoreBackup = (deviceId: string, backupId: string, confirm = false) =>
  req<{ detail: string }>(`/devices/${deviceId}/backups/${backupId}/restore`, {
    method: "POST",
    body: JSON.stringify({ confirm }),
  });

// --- Admin dev tools (simulated test devices + drive replay) ----------------------------------
export const listSimDevices = () => req<DeviceSummary[]>("/admin/dev/sim-devices");
export const createSimDevice = (alias: string) =>
  req<DeviceSummary>("/admin/dev/sim-devices", { method: "POST", body: JSON.stringify({ alias }) });
export const deleteSimDevice = (id: string) =>
  req<{ message: string }>(`/admin/dev/sim-devices/${id}`, { method: "DELETE" });
export const replayDrive = (deviceId: string, routeId: string, speedFactor = 4.0) =>
  req<{ message: string; points: number }>(`/admin/dev/sim-devices/${deviceId}/replay`, {
    method: "POST",
    body: JSON.stringify({ route_id: routeId, speed_factor: speedFactor }),
  });
export const stopReplay = (deviceId: string) =>
  req<{ message: string; stopped: boolean }>(`/admin/dev/sim-devices/${deviceId}/replay/stop`, {
    method: "POST",
  });
