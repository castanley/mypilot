// Single source of truth for device state across the app. One WebSocket subscription patches one
// normalized device map; pages read derived selectors instead of each hand-rolling a subscribeRealtime
// handler (which left gaps — e.g. the dashboard ignored `presence`, so an offline device stayed "online"
// until a refresh). Add a new event type → handle it here once and every page stays correct.
//
// Seed it synchronously from each page's SSR loader data (seedDevices / seedDriving) so first render
// matches the server markup (no flash). The realtime feed (subscribeRealtime) is already a ref-counted
// singleton; we attach to it once for the app's lifetime.

import { derived, writable } from "svelte/store";
import { browser } from "$app/environment";
import { subscribeRealtime, subscribeDeviceEvents, onRealtimeOpen } from "$lib/realtime";
import { getDevices } from "$lib/api";
import type { DeviceSummary, DeviceDetail, RealtimeEvent, Subsystems } from "$lib/types";

export type DeviceNode = {
  // summary (seeded from DeviceSummary; presence/device_status keep it current)
  id: string;
  alias: string;
  status: string;
  platform: string | null;
  software_version: string | null;
  branch: string | null;
  is_simulated: boolean;
  created_at: string;
  online: boolean;
  onroad: boolean;
  last_heartbeat_at: string | null;
  // live driving telemetry (the full subsystems tree + the flattened bits the hero/detail read)
  subsystems: Subsystems | null;
  speed_ms: number | null;
  heading_deg: number | null;
  latitude: number | null;
  longitude: number | null;
  gear: string | null; // PRNDL: park|drive|reverse|neutral|...
  track: [number, number][]; // == live_track; server sends the whole simplified trail each beat
  replaying: boolean;
  // detail-only (present when seeded from a DeviceDetail)
  hardware_id?: string | null;
  activated_at?: string | null;
};

type DevicesState = Record<string, DeviceNode>;

const internal = writable<DevicesState>({});

function blankNode(id: string): DeviceNode {
  return {
    id, alias: "", status: "active", platform: null, software_version: null, branch: null,
    is_simulated: false, created_at: "", online: false, onroad: false, last_heartbeat_at: null,
    subsystems: null, speed_ms: null, heading_deg: null, latitude: null, longitude: null,
    gear: null, track: [], replaying: false,
  };
}

// ---- seeding (synchronous, from SSR loader data) --------------------------------------------------

// STATIC fields — always safe to refresh from a server fetch (they don't change over the WS feed).
function staticFields(d: DeviceSummary): Partial<DeviceNode> {
  return {
    id: d.id, alias: d.alias, status: d.status, platform: d.platform,
    software_version: d.software_version, branch: d.branch, is_simulated: d.is_simulated,
    created_at: d.created_at,
  };
}
// LIVE fields — owned by the realtime feed once the WS is connected. Only seeded for a NEW node
// (initial paint); never overwritten on an existing node, or a list-refetch (e.g. the developer
// page's reactive seedDevices(sims)) would stomp live onroad/online with stale server values.
function liveFields(d: DeviceSummary): Partial<DeviceNode> {
  return { online: d.online, onroad: d.onroad, last_heartbeat_at: d.last_heartbeat_at };
}

/** Merge devices (summary or detail) into the map. Static fields always refresh; in the BROWSER,
 *  live fields seed only for new nodes (the WS owns them after that). A DeviceDetail's status_detail
 *  is a fresh telemetry snapshot and IS applied (at least as current as the last WS beat).
 *
 *  ON THE SERVER (SSR) the `internal` store is a MODULE SINGLETON shared across every request, and
 *  there is no WS to own live fields — so "preserve existing live state" would leak one request's
 *  driving node into the next request's render (a parked device flashing its old drive on first
 *  paint, then the client clearing it). During SSR we therefore ALWAYS take the request's own live
 *  fields (and reset any stale ones), so the server HTML reflects only this request's data. */
export function seedDevices(list: (DeviceSummary | DeviceDetail)[]): void {
  internal.update((m) => {
    const next = { ...m };
    for (const d of list) {
      // ON THE SERVER, always rebuild the node from this request's own data (blank base + the
      // request's live fields), never preserving the existing node — the module-singleton store is
      // shared across SSR requests, so preserving a prior request's live `onroad`/coords would flash
      // a parked device's old drive on first paint (then the client clears it). In the BROWSER we
      // preserve the existing node so the WS-owned live state isn't stomped by a list refetch.
      const existing = browser ? next[d.id] : undefined;
      const node = existing
        ? { ...existing, ...staticFields(d) }              // browser: keep live state, refresh static
        : { ...blankNode(d.id), ...staticFields(d), ...liveFields(d) }; // new node / SSR: fresh live
      // A full DeviceDetail carries a fresh telemetry snapshot + extra fields. On SSR this is what
      // makes a genuinely-driving device paint its hero; a parked device has no status_detail so it
      // stays blank (no flash).
      const det = d as DeviceDetail;
      if (det.status_detail) applyStatusInto(node, det.status_detail as Partial<DeviceNodeStatus>);
      if ("hardware_id" in det) node.hardware_id = det.hardware_id;
      if ("activated_at" in det) node.activated_at = det.activated_at;
      next[d.id] = node;
    }
    return next;
  });
}

/** Re-sync authoritative device state from GET /devices, OVERWRITING the live fields. The realtime
 *  feed is push-only and the browser throttles/suspends the WS while the tab is backgrounded, so the
 *  client misses events (e.g. a drive ending) and the store goes stale — the live map card lingering
 *  after a drive is the classic symptom. Called on tab-visible + WS-reopen to catch up. Unlike
 *  seedDevices (which preserves live fields), this trusts the server snapshot: it sets online/onroad/
 *  heartbeat, and for any device the server reports NOT onroad it clears the live driving bits so the
 *  hero/map hide. subsystems/track aren't on the summary, so a parked device's stale trail is dropped. */
export async function resyncDevices(): Promise<void> {
  if (!browser) return;
  let list: DeviceSummary[];
  try {
    list = await getDevices();
  } catch {
    return; // transient; the next visibility/reopen will retry
  }
  const seen = new Set(list.map((d) => d.id));
  internal.update((m) => {
    const next = { ...m };
    for (const d of list) {
      const node = { ...(next[d.id] ?? blankNode(d.id)), ...staticFields(d) };
      node.online = d.online;
      node.onroad = d.onroad;
      node.last_heartbeat_at = d.last_heartbeat_at;
      if (!d.onroad) {
        // Authoritatively parked: drop any stale live driving state from missed events.
        node.speed_ms = node.heading_deg = node.latitude = node.longitude = null;
        node.gear = null;
        node.track = [];
        node.replaying = false;
        if (node.subsystems?.driving) node.subsystems = { ...node.subsystems, driving: null };
      }
      next[d.id] = node;
    }
    // A device the server no longer lists (unpaired while we were away) -> mark revoked so it drops
    // out of visibleDevices/drivers.
    for (const id of Object.keys(next)) {
      if (!seen.has(id) && next[id].status !== "revoked") next[id] = { ...next[id], status: "revoked" };
    }
    return next;
  });
}

/** Dashboard hero seed: a map of device_id -> DeviceDetail for devices already driving. */
export function seedDriving(seed: Record<string, DeviceDetail>): void {
  seedDevices(Object.values(seed ?? {}));
}

// ---- reducer --------------------------------------------------------------------------------------

// The realtime device_status payload (Partial<DeviceStatusOut>) + what seedDevices pulls from a detail.
type DeviceNodeStatus = {
  online?: boolean;
  onroad?: boolean;
  last_heartbeat_at?: string | null;
  replaying?: boolean;
  subsystems?: Subsystems | null;
  live_track?: [number, number][];
};

/** Fold a device_status / status_detail payload into a node in place. subsystems + track are FULL
 *  replaces (the API sends the whole tree + whole simplified trail every beat — never deltas). */
function applyStatusInto(node: DeviceNode, s: DeviceNodeStatus): void {
  if (s.last_heartbeat_at != null) node.last_heartbeat_at = s.last_heartbeat_at;
  if (typeof s.onroad === "boolean") node.onroad = s.onroad;
  if (typeof s.online === "boolean") node.online = s.online;
  if (typeof s.replaying === "boolean") node.replaying = s.replaying;
  if (s.subsystems !== undefined) node.subsystems = s.subsystems;
  // subsystems is a FULL replace, so the flattened mirror must track it: when subsystems arrives
  // WITHOUT driving (parked/offroad beat), clear the flattened fields too — else stale lat/lon could
  // keep a device in the `drivers` hero with last-drive coordinates.
  if (s.subsystems !== undefined) {
    const dr = s.subsystems?.driving;
    node.speed_ms = dr?.speed_ms ?? null;
    node.heading_deg = dr?.heading_deg ?? null;
    node.latitude = dr?.latitude ?? null;
    node.longitude = dr?.longitude ?? null;
    node.gear = dr?.gear ?? null;
  }
  if (s.live_track !== undefined) node.track = s.live_track ?? [];
}

/** Fold one realtime event (device_status / presence) into the device map. This IS the store's
 *  reducer — exported so it's both the subscription handler (below) and directly unit-testable. */
export function applyRealtimeEvent(e: RealtimeEvent): void {
  internal.update((m) => {
    // Don't synthesize unknown devices — they appear only once a page has seeded them from its loader.
    const node = m[e.device_id];
    if (!node) return m;
    const next = { ...node };
    if (e.type === "device_status") {
      applyStatusInto(next, e.status as DeviceNodeStatus);
    } else if (e.type === "presence") {
      next.online = e.online;
      if (!e.online) {
        // An offline device isn't driving: clear onroad + live position so the dashboard hero (reads
        // the flattened lat/lon) AND the detail live map (reads subsystems.driving.lat/lon) both hide
        // immediately on a mid-drive drop — not only on a clean offroad heartbeat. Clear BOTH mirrors
        // of position. Keep the trail (track) as last-known.
        next.onroad = false;
        next.latitude = null;
        next.longitude = null;
        next.speed_ms = null;
        next.heading_deg = null;
        next.gear = null;
        next.replaying = false;
        if (next.subsystems?.driving) {
          next.subsystems = { ...next.subsystems, driving: null };
        }
      }
    } else {
      return m; // device_event handled via subscribeDeviceEvents, not the device map
    }
    return { ...m, [e.device_id]: next };
  });
}

// Attach to the realtime feed once for the app's lifetime (the socket itself is ref-counted in
// realtime.ts). Browser-only; on the server the store stays at its seeded snapshot.
if (browser) {
  subscribeRealtime(applyRealtimeEvent);
  // Catch up on events missed while the WS was closed/throttled: re-sync when it (re)connects and
  // when the tab returns to the foreground (backgrounding suspends the socket, so a drive that ended
  // while hidden would otherwise leave the live map card stuck until a manual refresh).
  onRealtimeOpen(() => {
    void resyncDevices();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void resyncDevices();
  });
  // Authoritative catch-up on every mount (not only visibility/WS-reopen): a plain refresh of an
  // already-visible tab may not trigger either, and the server snapshot is presence-clamped, so this
  // reconciles any node that slipped through within one fetch — closing the phantom on refresh.
  void resyncDevices();
}

// ---- public selectors -----------------------------------------------------------------------------

export const devices = { subscribe: internal.subscribe };

/** All non-revoked devices (the list/dashboard view). */
export const visibleDevices = derived(internal, ($m) =>
  Object.values($m).filter((n) => n.status !== "revoked"),
);

// The dashboard live-map hero shows any device that's ON and sending coordinates — whether moving or
// parked-but-running. Gate purely on a live position (onroad + a GPS fix), NOT on speed: the user wants
// to see the car on the map whenever it's powered and located, and the speed readout shows 0 when stopped.
export const drivers = derived(internal, ($m) =>
  Object.values($m).filter(
    (n) =>
      n.status !== "revoked" &&
      n.onroad &&
      n.latitude != null &&
      n.longitude != null,
  ),
);

// `devices` (the raw map) is read as `$devices[id]` by the detail page for a single node.

// Re-export the device-event passthrough so pages (drives/logs) keep one socket, not their own.
export { subscribeDeviceEvents };

/** Reset the store to empty — TEST ONLY (the store is a module singleton; tests need isolation). */
export function __resetForTests(): void {
  internal.set({});
}
