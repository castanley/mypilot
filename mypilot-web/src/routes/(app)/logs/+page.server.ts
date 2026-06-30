import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { DeviceSummary, LogOut } from "$lib/types";

// SSR: device logs for the selected device (?device=…, else the first device).
export const load: PageServerLoad = async ({ request, url }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const devices = await serverGet<DeviceSummary[]>("/devices", cookie).catch(
    () => [] as DeviceSummary[],
  );
  const wanted = url.searchParams.get("device");
  const selected = (wanted && devices.find((d) => d.id === wanted)?.id) || devices[0]?.id || "";
  const logs = selected
    ? await serverGet<LogOut[]>(`/devices/${selected}/logs`, cookie).catch(() => [] as LogOut[])
    : [];
  return { devices, selected, logs };
};
