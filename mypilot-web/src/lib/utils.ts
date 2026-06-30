export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function relTime(iso: string | null): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const s = Math.round(diff / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function fullDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// "Today" / "Yesterday" / "Mon, Jun 24" — for grouping drives by day.
export function dayLabel(iso: string | null): string {
  if (!iso) return "Unknown date";
  const d = new Date(iso);
  const today = new Date();
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diffDays = Math.round((startOf(today) - startOf(d)) / 86400000);
  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

// Clock time only, e.g. "2:14 PM" — for a drive within a day group.
export function clockTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function shortId(id: string, head = 6, tail = 4): string {
  if (id.length <= head + tail + 1) return id;
  return `${id.slice(0, head)}…${id.slice(-tail)}`;
}

// Split a MyPilot device version like "sunnypilot-2026.002.000-mypilot-2026.06.26-18" into a
// readable upstream "core" label + the MyPilot build (date + per-day counter). The base tag is
// spelled out (sunnypilot/frogpilot/openpilot); legacy short tags (sp/fp/op) still parse.
// Falls back gracefully for any unrecognized format (returns the whole string as core, no mypilot).
const BASE_NAMES: Record<string, string> = {
  sunnypilot: "SunnyPilot", frogpilot: "FrogPilot", openpilot: "openpilot",
  sp: "SunnyPilot", fp: "FrogPilot", op: "openpilot",
};
export function parseVersion(version: string | null): { core: string; mypilot: string | null } {
  if (!version) return { core: "—", mypilot: null };
  const m = version.match(/^(sunnypilot|frogpilot|openpilot|sp|fp|op)-(.+?)-mypilot-(.+)$/);
  if (!m) return { core: version, mypilot: null };
  const [, tag, upstream, date] = m;
  return { core: `${BASE_NAMES[tag] ?? tag} ${upstream}`, mypilot: `MyPilot ${date}` };
}

export function humanizeAction(action: string): string {
  return action
    .replace(/[._]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i > 0 && v < 10 ? 1 : 0)} ${units[i]}`;
}

export function fmtDuration(s: number | null | undefined): string {
  if (!s) return "—";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${sec}s`;
  return `${sec}s`;
}

export function fmtDistance(m: number | null | undefined): string {
  if (m == null) return "—";
  const km = m / 1000;
  return km >= 1 ? `${km.toFixed(1)} km` : `${Math.round(m)} m`;
}

// Live vehicle speed. The agent reports m/s (driving.speed_ms); show mph (US fleet). null/absent
// off-device or offroad -> em dash.
export function fmtSpeed(ms: number | null | undefined): string {
  if (ms == null) return "—";
  return `${Math.round(ms * 2.236936)} mph`;
}

// PRNDL gear label from carState.gearShifter (park|drive|reverse|neutral|...). Title-cased for display.
const GEAR_LABELS: Record<string, string> = {
  park: "Park", drive: "Drive", reverse: "Reverse", neutral: "Neutral",
  sport: "Sport", low: "Low", brake: "Brake", eco: "Eco",
};
export function gearLabel(gear: string | null | undefined): string | null {
  if (!gear) return null;
  return GEAR_LABELS[gear] ?? gear.charAt(0).toUpperCase() + gear.slice(1);
}

// Live travel heading. The agent reports degrees (0=N, 90=E); show as a cardinal + degrees,
// e.g. fmtHeading(88) -> "E 88°". null/absent (slow/parked/no fix) -> em dash.
const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
export function fmtHeading(deg: number | null | undefined): string {
  if (deg == null) return "—";
  const d = ((deg % 360) + 360) % 360;
  return `${COMPASS[Math.round(d / 45) % 8]} ${Math.round(d)}°`;
}

export function thermalKind(status: string | null): "success" | "warning" | "danger" | "neutral" {
  if (!status) return "neutral";
  const v = status.toLowerCase();
  if (v.includes("green") || v.includes("good")) return "success";
  if (v.includes("yellow") || v.includes("warm")) return "warning";
  if (v.includes("red") || v.includes("hot") || v.includes("danger")) return "danger";
  return "neutral";
}

// GPS status reported by the agent. The GNSS daemon usually only runs onroad, so "no_signal"
// (parked) is normal, not an error.
export function gpsLabel(status: string | null): string {
  switch (status) {
    case "has_fix":
      return "Fix acquired";
    case "searching":
      return "Searching…";
    case "no_signal":
      return "No signal";
    default:
      return status ?? "—";
  }
}
