import type { LayoutServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { DeviceSummary } from "$lib/types";

// Expose the device fleet to the whole authenticated shell so the sidebar/dashboard can link
// straight to the lone device when there's exactly one — clicking "Devices" then navigates ONCE to
// /devices/{id} instead of going to /devices and bouncing through the single-device redirect (which
// the user sees as a URL "blip"). `soleDeviceId` is the id when exactly one non-revoked device exists,
// else null. The /devices loader keeps its redirect as a fallback for typed URLs / bookmarks (a full
// page load redirects server-side with no visible blip).
export const load: LayoutServerLoad = async ({ request }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const devices = await serverGet<DeviceSummary[]>("/devices", cookie).catch(
    () => [] as DeviceSummary[],
  );
  const active = devices.filter((d) => d.status !== "revoked");
  return { soleDeviceId: active.length === 1 ? active[0].id : null };
};
