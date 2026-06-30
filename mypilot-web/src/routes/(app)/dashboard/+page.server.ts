import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { AuditEventOut, DeviceDetail, DeviceSummary, HealthResponse } from "$lib/types";

// SSR: the dashboard paints with real data on first byte. Realtime updates apply client-side.
export const load: PageServerLoad = async ({ request, parent }) => {
  const cookie = request.headers.get("cookie") ?? "";
  // The deployment health (counts/sizes) + the audit log are ADMIN-ONLY surfaces — only the admin
  // fetches them (the endpoints 403 otherwise, and we don't even ask). Everyone sees their own
  // devices.
  const { user } = await parent();
  const isAdmin = !!user?.is_admin;
  const [devices, health, audit] = await Promise.all([
    serverGet<DeviceSummary[]>("/devices", cookie).catch(() => [] as DeviceSummary[]),
    isAdmin
      ? serverGet<HealthResponse>("/admin/health", cookie).catch(() => null)
      : Promise.resolve(null),
    isAdmin
      ? serverGet<AuditEventOut[]>("/admin/audit", cookie).catch(() => [] as AuditEventOut[])
      : Promise.resolve([] as AuditEventOut[]),
  ]);
  // Seed the "On the road now" hero on first paint: for devices already driving, pull their full
  // status_detail (the summary has no telemetry) so speed/heading/position render immediately rather
  // than waiting for the first realtime heartbeat. Small N (only the onroad ones).
  const driving = devices.filter((d) => d.onroad);
  const details = await Promise.all(
    driving.map((d) =>
      serverGet<DeviceDetail>(`/devices/${d.id}`, cookie).catch(() => null),
    ),
  );
  const drivingSeed: Record<string, DeviceDetail> = {};
  for (const det of details) if (det) drivingSeed[det.id] = det;
  return { devices, health, audit: audit.slice(0, 6), drivingSeed };
};
