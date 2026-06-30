import { env } from "$env/dynamic/private";
import type { Handle } from "@sveltejs/kit";

const API = env.INTERNAL_API_URL || "http://mypilot-api:8000";

// Server-side session resolution: forward the session cookie to the internal API,
// populate locals.user (SSR auth guard) and detect first-run setup.
export const handle: Handle = async ({ event, resolve }) => {
  event.locals.user = null;
  event.locals.needsSetup = false;

  const cookie = event.request.headers.get("cookie") ?? "";
  try {
    const meRes = await fetch(`${API}/api/me`, { headers: { cookie } });
    if (meRes.ok) event.locals.user = await meRes.json();
  } catch {
    /* API unreachable -> treat as logged out */
  }

  if (!event.locals.user) {
    try {
      const stateRes = await fetch(`${API}/api/auth/setup-state`);
      if (stateRes.ok) {
        const state = await stateRes.json();
        event.locals.needsSetup = Boolean(state.needs_setup);
      }
    } catch {
      /* ignore */
    }
  }

  return resolve(event);
};
