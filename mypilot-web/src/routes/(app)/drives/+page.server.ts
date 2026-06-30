import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { DeviceSummary, RouteSummary } from "$lib/types";

// SSR: drives (routes that have recorded video) for the selected device, painted on first byte.
export const load: PageServerLoad = async ({ request, url }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const devices = await serverGet<DeviceSummary[]>("/devices", cookie).catch(
    () => [] as DeviceSummary[],
  );
  const wanted = url.searchParams.get("device");
  const selected = (wanted && devices.find((d) => d.id === wanted)?.id) || devices[0]?.id || "";
  const routes = selected
    ? await serverGet<RouteSummary[]>(`/devices/${selected}/routes`, cookie).catch(
        () => [] as RouteSummary[],
      )
    : [];
  return { devices, selected, routes };
};
