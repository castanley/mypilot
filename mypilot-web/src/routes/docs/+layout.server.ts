import type { LayoutServerLoad } from "./$types";
import { loadSite } from "$lib/server/api";

// Docs wiki is public. Branding comes from /public/site; `user` (for the CTA) comes from the
// root layout.
export const load: LayoutServerLoad = async ({ request }) => {
  const site = await loadSite(request.headers.get("cookie") ?? "");
  return { site };
};
