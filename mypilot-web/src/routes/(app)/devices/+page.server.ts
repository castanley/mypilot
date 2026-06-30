import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";
import { base } from "$app/paths";
import { serverGet } from "$lib/server/api";
import type { DeviceSummary } from "$lib/types";

// SSR: the device list paints populated on first byte; realtime updates apply client-side.
export const load: PageServerLoad = async ({ request, url }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const devices = await serverGet<DeviceSummary[]>("/devices", cookie).catch(
    () => [] as DeviceSummary[],
  );
  // With exactly one device, the list is a pointless extra click — jump straight to it. The detail
  // page's back-link uses ?all to force the list (so you can still get here to pair a second device);
  // honour that override and never redirect when there are 0 or 2+ devices.
  if (devices.length === 1 && !url.searchParams.has("all")) {
    throw redirect(307, `${base}/devices/${devices[0].id}`);
  }
  return { devices };
};
