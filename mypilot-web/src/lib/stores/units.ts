import { browser } from "$app/environment";
import { writable } from "svelte/store";

// Temperature unit preference. The agent reports °C; we convert in the UI per this preference.
export type TempUnit = "C" | "F";

const STORAGE_KEY = "mypilot-temp-unit";

function initial(): TempUnit {
  if (!browser) return "C";
  const saved = localStorage.getItem(STORAGE_KEY);
  return saved === "F" || saved === "C" ? saved : "C";
}

export const tempUnit = writable<TempUnit>(initial());

export function setTempUnit(value: TempUnit) {
  if (browser) localStorage.setItem(STORAGE_KEY, value);
  tempUnit.set(value);
}

export function toggleTempUnit() {
  tempUnit.update((v) => {
    const next: TempUnit = v === "C" ? "F" : "C";
    if (browser) localStorage.setItem(STORAGE_KEY, next);
    return next;
  });
}

// Format a Celsius value in the chosen unit, e.g. fmtTemp(40.7, "F") -> "105°F".
export function fmtTemp(celsius: number | null | undefined, unit: TempUnit): string {
  if (celsius == null) return "—";
  const v = unit === "F" ? celsius * 9 / 5 + 32 : celsius;
  return `${Math.round(v)}°${unit}`;
}
