import { redirect } from "@sveltejs/kit";
import type { PageServerLoad } from "./$types";
import { base } from "$app/paths";
import { serverGet } from "$lib/server/api";
import type { DeviceSummary, RouteSummary } from "$lib/types";

// Admin-only dev tools. Non-admins are bounced to the dashboard (the API also enforces admin, so this
// is just UX). SSR the sim-device list + the routes that have a GPS track (replay sources).
export const load: PageServerLoad = async ({ request, parent }) => {
  const { user } = await parent();
  if (!user?.is_admin) throw redirect(307, `${base}/dashboard`);
  const cookie = request.headers.get("cookie") ?? "";
  const [sims, routes] = await Promise.all([
    serverGet<DeviceSummary[]>("/admin/dev/sim-devices", cookie).catch(() => [] as DeviceSummary[]),
    serverGet<RouteSummary[]>("/routes?has_track=true", cookie).catch(() => [] as RouteSummary[]),
  ]);
  return { sims, routes };
};
