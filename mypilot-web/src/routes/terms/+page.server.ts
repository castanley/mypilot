import type { PageServerLoad } from "./$types";
import { loadSite } from "$lib/server/api";

// Terms of Service is a public, no-auth page (the device QR / onboarding links here without a
// session). Branding (project_name) comes from /public/site so a fork shows its own name.
export const load: PageServerLoad = async ({ request }) => {
  const site = await loadSite(request.headers.get("cookie") ?? "");
  return { site };
};
