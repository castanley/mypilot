import type { PageServerLoad } from "./$types";
import { serverGet } from "$lib/server/api";
import type { RouteSummary } from "$lib/types";

// SSR: all the caller's drives that have a GPS track, for the all-drives overview map. Light
// scalars only (start_lat/start_lon) — the full polyline for a drive is fetched lazily on that
// drive's own page. Owner-scoping is enforced server-side by GET /api/routes (Device-join).
export const load: PageServerLoad = async ({ request }) => {
  const cookie = request.headers.get("cookie") ?? "";
  const items = await serverGet<RouteSummary[]>("/routes?has_track=true", cookie).catch(
    () => [] as RouteSummary[],
  );
  return { items };
};
