// Unit tests for the realtime device store — the reducer + selectors that decide whether a device
// shows as "driving" on the dashboard live map. This is the client half of the phantom-liveness
// defense: even though the server is now authoritative (presence-clamped serializer), the store must
// not RE-introduce stale driving state from a missed/late event. In the test (Node) env `browser` is
// false, so the WS-subscription side-effects don't run and we test the pure logic.

import { describe, expect, it, beforeEach } from "vitest";
import { get } from "svelte/store";
import {
  devices,
  drivers,
  visibleDevices,
  seedDevices,
  seedDriving,
  applyRealtimeEvent,
  __resetForTests,
} from "./devices";
import type { DeviceSummary, DeviceDetail, RealtimeEvent } from "$lib/types";

// applyRealtimeEvent is the store's real reducer — the same function the WS subscription calls.
const emit = (e: RealtimeEvent) => applyRealtimeEvent(e);

const summary = (over: Partial<DeviceSummary> = {}): DeviceSummary => ({
  id: "d1",
  alias: "RAM",
  status: "active",
  platform: "Chrysler Ram Hd",
  software_version: null,
  branch: null,
  created_at: "",
  is_simulated: false,
  online: true,
  onroad: false,
  last_heartbeat_at: null,
  ...over,
});

const drivingDetail = (over: Partial<DeviceDetail> = {}): DeviceDetail =>
  ({
    ...summary({ onroad: true }),
    hardware_id: null,
    activated_at: null,
    status_detail: {
      online: true,
      onroad: true,
      last_heartbeat_at: null,
      updated_at: null,
      captured_at: null,
      replaying: false,
      live_track: [[37.5, -122.3]],
      subsystems: {
        driving: { speed_ms: 20, heading_deg: 90, latitude: 37.5, longitude: -122.3, gear: "drive" },
      },
    },
    ...over,
  }) as DeviceDetail;

beforeEach(() => __resetForTests());

describe("drivers selector", () => {
  it("includes an onroad device with a GPS fix", () => {
    seedDevices([drivingDetail()]);
    expect(get(drivers).map((d) => d.id)).toEqual(["d1"]);
  });

  it("excludes a parked (offroad) device even if coords linger", () => {
    seedDevices([summary({ onroad: false })]);
    expect(get(drivers)).toHaveLength(0);
  });

  it("excludes an onroad device with no position yet (GPS warmup)", () => {
    const d = drivingDetail();
    d.status_detail!.subsystems = { driving: { speed_ms: 0, heading_deg: null, latitude: null, longitude: null, gear: null } };
    seedDevices([d]);
    expect(get(drivers)).toHaveLength(0);
  });
});

describe("presence:false clears live driving (mid-drive drop)", () => {
  it("drops the device off the live map and clears position/onroad", () => {
    seedDevices([drivingDetail()]);
    expect(get(drivers)).toHaveLength(1);

    emit({ type: "presence", device_id: "d1", online: false });

    const node = get(devices)["d1"];
    expect(node.online).toBe(false);
    expect(node.onroad).toBe(false);
    expect(node.latitude).toBeNull();
    expect(node.longitude).toBeNull();
    expect(node.subsystems?.driving ?? null).toBeNull();
    expect(get(drivers)).toHaveLength(0);
  });
});

describe("device_status reducer", () => {
  it("an offroad status beat clears the flattened live fields (no stale lat/lon in the hero)", () => {
    seedDevices([drivingDetail()]);
    // Server sends a fresh, presence-clamped beat: parked, driving nulled.
    emit({
      type: "device_status",
      device_id: "d1",
      status: { online: true, onroad: false, subsystems: { driving: null }, live_track: [] },
    });
    const node = get(devices)["d1"];
    expect(node.onroad).toBe(false);
    expect(node.latitude).toBeNull();
    expect(node.speed_ms).toBeNull();
    expect(get(drivers)).toHaveLength(0);
  });

  it("a live onroad beat populates the flattened fields and the hero", () => {
    seedDevices([summary({ onroad: false })]);
    emit({
      type: "device_status",
      device_id: "d1",
      status: {
        online: true,
        onroad: true,
        subsystems: { driving: { speed_ms: 13, heading_deg: 270, latitude: 1, longitude: 2, gear: "drive" } },
        live_track: [[1, 2]],
      },
    });
    const node = get(devices)["d1"];
    expect(node.onroad).toBe(true);
    expect(node.latitude).toBe(1);
    expect(node.speed_ms).toBe(13);
    expect(get(drivers).map((d) => d.id)).toEqual(["d1"]);
  });
});

describe("visibleDevices", () => {
  it("hides revoked devices", () => {
    seedDevices([summary()]);
    expect(get(visibleDevices)).toHaveLength(1);
    emit({ type: "presence", device_id: "d1", online: false });
    // still visible (offline != revoked)
    expect(get(visibleDevices)).toHaveLength(1);
  });
});

// In this test env `browser` is false, so seedDevices takes the SSR path: the module-singleton store
// is shared across requests on the server, so a seed must reflect ONLY the current request's data —
// never leak a previous request's driving node (the "flash then hide" bug: a parked device briefly
// shows its old drive in the SSR HTML, then the client clears it).
describe("SSR seed is request-authoritative (no cross-request flash)", () => {
  it("a now-parked device does NOT inherit a previous seed's driving state", () => {
    // Request A: device d1 was driving.
    seedDevices([drivingDetail()]);
    expect(get(drivers).map((d) => d.id)).toEqual(["d1"]);
    // Request B (later): the same device is now parked (summary onroad=false, no detail).
    seedDevices([summary({ onroad: false })]);
    const node = get(devices)["d1"];
    expect(node.onroad).toBe(false);
    expect(node.latitude).toBeNull();
    expect(node.longitude).toBeNull();
    expect(node.speed_ms).toBeNull();
    expect((node.track ?? []).length).toBe(0);
    expect(get(drivers)).toHaveLength(0); // <- the bug: would be 1 (stale driver) before the fix
  });

  it("a re-listed device that's now parked shows parked, even if a prior request had it driving", () => {
    // The reported flash: a device driving in one request, parked in the next. The new (parked) seed
    // must win — the device must not render as a stale driver.
    seedDevices([drivingDetail({ id: "old" } as Partial<DeviceDetail>)]);
    seedDevices([summary({ id: "old", onroad: false })]); // same device, now parked
    const node = get(devices)["old"];
    expect(node.onroad).toBe(false);
    expect(node.latitude).toBeNull();
    expect(get(drivers)).toHaveLength(0);
  });

  it("the dashboard's two-step seed keeps BOTH a parked and a driving device", () => {
    // Exactly what dashboard/+page.svelte does on SSR: seed the full list, then seed the driving
    // subset with detail. The parked device must survive the second seed (not be reset away).
    const parked = summary({ id: "p1", onroad: false });
    const driving = drivingDetail({ id: "d2" } as Partial<DeviceDetail>);
    seedDevices([parked, summary({ id: "d2", onroad: true })]); // full list
    seedDriving({ d2: driving }); // driving subset with detail
    const ids = get(visibleDevices).map((d) => d.id).sort();
    expect(ids).toEqual(["d2", "p1"]); // both present
    expect(get(drivers).map((d) => d.id)).toEqual(["d2"]); // only d2 drives
  });
});
