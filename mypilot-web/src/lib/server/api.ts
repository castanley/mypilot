// Server-side API access for SSR loads. Calls the internal API directly and forwards the
// caller's session cookie (the browser's same-origin /api proxy isn't reachable from SSR).
import { env } from "$env/dynamic/private";

const API = env.INTERNAL_API_URL || "http://mypilot-api:8000";

export async function serverGet<T>(path: string, cookie: string): Promise<T> {
  // cache: "no-store" is REQUIRED. This uses the global fetch (not load's request-scoped fetch), so
  // without it Node/undici caches responses across requests and the SSR page renders frozen stale data
  // (the dashboard kept showing a sim "driving at 45 mph" long after it parked, until the web process
  // restarted). Device status is live; never serve a cached snapshot.
  const res = await fetch(`${API}/api${path}`, { headers: { cookie }, cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return (await res.json()) as T;
}

export interface PublicSite {
  project_name: string;
  stack_url: string;
  source_url: string;
}

// Non-sensitive branding for public (no-auth) pages — the landing and the docs wiki. Falls back
// to MyPilot defaults if the API is unreachable so the marketing/docs site still renders.
export async function loadSite(cookie: string): Promise<PublicSite> {
  try {
    return await serverGet<PublicSite>("/public/site", cookie);
  } catch {
    return { project_name: "MyPilot", stack_url: "", source_url: "" };
  }
}
