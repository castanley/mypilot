import { browser } from "$app/environment";
import { writable } from "svelte/store";

export type Theme = "dark" | "light";

const STORAGE_KEY = "mypilot-theme";

function initial(): Theme {
  if (!browser) return "dark";
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved === "light" || saved === "dark") return saved;
  return "dark";
}

export const theme = writable<Theme>(initial());

export function applyTheme(value: Theme) {
  if (!browser) return;
  const root = document.documentElement;
  root.classList.remove("dark", "light");
  root.classList.add(value);
  root.style.colorScheme = value;
  localStorage.setItem(STORAGE_KEY, value);
}

export function toggleTheme() {
  theme.update((v) => {
    const next: Theme = v === "dark" ? "light" : "dark";
    applyTheme(next);
    return next;
  });
}

if (browser) {
  theme.subscribe((v) => applyTheme(v));
}
