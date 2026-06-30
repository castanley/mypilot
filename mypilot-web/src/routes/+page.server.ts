import type { PageServerLoad } from "./$types";
import { loadSite } from "$lib/server/api";

// Public landing page — no auth. Loads non-sensitive branding so a fork's site reflects its own
// project name / Stack URL / source link. `data.user` (from the layout) decides the CTA.
export const load: PageServerLoad = async ({ request }) => {
  const site = await loadSite(request.headers.get("cookie") ?? "");
  return { site };
};
