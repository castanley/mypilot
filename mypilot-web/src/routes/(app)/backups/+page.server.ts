import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { BackupOut, DeviceSummary } from "$lib/types";

// SSR: all settings backups + the device list (create lives on each device's Backups tab).
export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const [backups, devices] = await Promise.all([
    serverGet<BackupOut[]>("/backups", cookie).catch(() => [] as BackupOut[]),
    serverGet<DeviceSummary[]>("/devices", cookie).catch(() => [] as DeviceSummary[]),
  ]);
  return { backups, devices };
};
