import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { AuditEventOut, DeviceDetail } from "$lib/types";

// SSR: the device detail paints with real data on the first byte instead of flashing a skeleton
// while the client fetches (which it did, being the one (app) page with no server load — visible
// now that "Devices" links straight here for single-device accounts). Realtime + lazy per-tab
// loads (settings/models/etc.) still happen client-side. `device` is null on a 404 so the page
// renders its not-found state; audit failure is non-fatal (empty list).
export const load: PageServerLoad = async ({ params, request }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const device = await serverGet<DeviceDetail>(`/devices/${params.id}`, cookie).catch(() => null);
  const audit = device
    ? await serverGet<AuditEventOut[]>(`/devices/${params.id}/audit`, cookie).catch(
        () => [] as AuditEventOut[],
      )
    : [];
  return { device, audit };
};
