import { redirect } from "@sveltejs/kit";
import type { LayoutServerLoad } from "./$types";

// Public (no-auth) routes. "/" is the marketing/landing page, "/docs/*" is the wiki, and
// "/terms" is the Terms of Service the device links to during onboarding; auth pages render
// outside the shell.
const PUBLIC = new Set(["/", "/login", "/setup", "/terms"]);
const PUBLIC_PREFIXES = ["/docs"];
const AUTH_PAGES = new Set(["/login", "/setup"]);

export const load: LayoutServerLoad = async ({ locals, url }) => {
  const path = url.pathname;
  const isPublic =
    PUBLIC.has(path) || PUBLIC_PREFIXES.some((p) => path === p || path.startsWith(p + "/"));

  if (!locals.user && !isPublic) {
    // Preserve where the visitor was headed (path + query, e.g. /devices/pair?code=XXXX from a
    // scanned QR) so login can land them back there. Encoded as a single ?next= param.
    const target = url.pathname + url.search;
    const suffix = target && target !== "/" ? `?next=${encodeURIComponent(target)}` : "";
    throw redirect(303, (locals.needsSetup ? "/setup" : "/login") + suffix);
  }
  // First run: a brand-new instance has no admin yet, so /login would be a dead end -> send the
  // visitor straight to /setup (the register page). Once set up, /setup is pointless -> /login.
  if (!locals.user && path === "/login" && locals.needsSetup) {
    throw redirect(303, "/setup");
  }
  if (!locals.user && path === "/setup" && !locals.needsSetup) {
    throw redirect(303, "/login");
  }
  // Signed-in users don't need the login/setup pages -> send them on. Honor a safe ?next= (e.g.
  // back to /devices/pair?code=XXXX from a scanned QR), else the dashboard.
  if (locals.user && AUTH_PAGES.has(path)) {
    throw redirect(303, safeNext(url.searchParams.get("next")) ?? "/dashboard");
  }
  return { user: locals.user, needsSetup: locals.needsSetup };
};

// Only allow same-origin app paths as a redirect target (a leading single "/", not "//" or a
// scheme), so ?next= can't be abused for an open redirect.
function safeNext(next: string | null): string | null {
  if (!next) return null;
  if (!next.startsWith("/") || next.startsWith("//")) return null;
  return next;
}
