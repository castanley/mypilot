// Pure formatter unit tests — the live-telemetry display helpers (speed/heading/gear) the dashboard
// and detail pages render. Cheap, but they guard against unit/format regressions in user-facing data.

import { describe, expect, it } from "vitest";
import { fmtSpeed, fmtHeading, gearLabel, fmtDistance } from "./utils";

describe("fmtSpeed (m/s -> mph)", () => {
  it("converts and rounds", () => {
    expect(fmtSpeed(0)).toBe("0 mph");
    expect(fmtSpeed(20)).toBe("45 mph"); // 20 m/s ≈ 44.7 -> 45
  });
  it("renders em dash for null/undefined", () => {
    expect(fmtSpeed(null)).toBe("—");
    expect(fmtSpeed(undefined)).toBe("—");
  });
});

describe("fmtHeading (deg -> cardinal)", () => {
  it("maps degrees to compass points", () => {
    expect(fmtHeading(0)).toBe("N 0°");
    expect(fmtHeading(90)).toBe("E 90°");
    expect(fmtHeading(180)).toBe("S 180°");
    expect(fmtHeading(270)).toBe("W 270°");
  });
  it("normalizes out-of-range degrees into [0,360)", () => {
    expect(fmtHeading(360)).toBe("N 0°"); // 360 wraps to 0
    expect(fmtHeading(-90)).toBe("W 270°"); // -90 wraps to 270
  });
  it("em dash for null", () => {
    expect(fmtHeading(null)).toBe("—");
  });
});

describe("gearLabel (PRNDL)", () => {
  it("title-cases known gears", () => {
    expect(gearLabel("park")).toBe("Park");
    expect(gearLabel("drive")).toBe("Drive");
    expect(gearLabel("reverse")).toBe("Reverse");
    expect(gearLabel("neutral")).toBe("Neutral");
  });
  it("falls back to capitalized unknown, null for empty", () => {
    expect(gearLabel("manumatic")).toBe("Manumatic");
    expect(gearLabel(null)).toBeNull();
    expect(gearLabel(undefined)).toBeNull();
  });
});

describe("fmtDistance", () => {
  it("meters under 1km, km above", () => {
    expect(fmtDistance(500)).toBe("500 m");
    expect(fmtDistance(1500)).toBe("1.5 km");
    expect(fmtDistance(null)).toBe("—");
  });
});
