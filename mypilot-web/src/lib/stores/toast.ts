import { writable } from "svelte/store";

export type ToastKind = "success" | "error" | "info" | "warning";

export interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  description?: string;
  duration: number;
}

let counter = 0;

export const toasts = writable<Toast[]>([]);

export function dismissToast(id: number) {
  toasts.update((list) => list.filter((t) => t.id !== id));
}

export function pushToast(
  kind: ToastKind,
  title: string,
  description?: string,
  duration = 4200,
): number {
  const id = ++counter;
  toasts.update((list) => [...list, { id, kind, title, description, duration }]);
  if (duration > 0) {
    setTimeout(() => dismissToast(id), duration);
  }
  return id;
}

export const toast = {
  success: (t: string, d?: string) => pushToast("success", t, d),
  error: (t: string, d?: string) => pushToast("error", t, d),
  info: (t: string, d?: string) => pushToast("info", t, d),
  warning: (t: string, d?: string) => pushToast("warning", t, d),
};
