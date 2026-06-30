// Live device events over the real WebSocket (WS /api/realtime/web, same-origin,
// cookie-authenticated). Subscribers receive RealtimeEvent objects; the socket
// auto-reconnects while there are subscribers.

import { browser } from "$app/environment";
import type { RealtimeEvent } from "$lib/types";

type Listener = (e: RealtimeEvent) => void;

const listeners = new Set<Listener>();
// Fired when the socket (re)opens — push feeds drop events while the tab is backgrounded (the browser
// throttles/suspends the WS), so subscribers re-sync authoritative state on (re)connect to catch up.
const openListeners = new Set<() => void>();
let socket: WebSocket | null = null;
let stopped = false;
let retry: ReturnType<typeof setTimeout> | null = null;

function connect() {
  if (!browser || socket) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${proto}://${location.host}/api/realtime/web`);
  socket.onopen = () => {
    for (const l of openListeners) l();
  };
  socket.onmessage = (ev) => {
    let data: RealtimeEvent;
    try {
      data = JSON.parse(ev.data) as RealtimeEvent;
    } catch {
      return;
    }
    for (const l of listeners) l(data);
  };
  socket.onclose = () => {
    socket = null;
    if (!stopped && listeners.size > 0) retry = setTimeout(connect, 3000);
  };
  socket.onerror = () => socket?.close();
}

/** Register a callback fired whenever the realtime socket (re)connects. Returns an unsubscribe fn.
 *  Used to re-sync state that may have gone stale while the socket was closed/throttled. */
export function onRealtimeOpen(fn: () => void): () => void {
  openListeners.add(fn);
  return () => openListeners.delete(fn);
}

export function subscribeRealtime(fn: Listener): () => void {
  listeners.add(fn);
  stopped = false;
  connect();
  return () => {
    listeners.delete(fn);
    if (listeners.size === 0) {
      stopped = true;
      if (retry) {
        clearTimeout(retry);
        retry = null;
      }
      socket?.close();
      socket = null;
    }
  };
}

// Convenience: subscribe to just device_event frames (route_uploaded / log_uploaded / command_result)
// over the same single socket. Pages that only care about "something changed, refetch" (drives, logs)
// use this instead of filtering the full feed themselves.
export function subscribeDeviceEvents(
  fn: (e: Extract<RealtimeEvent, { type: "device_event" }>) => void,
): () => void {
  return subscribeRealtime((e) => {
    if (e.type === "device_event") fn(e);
  });
}
