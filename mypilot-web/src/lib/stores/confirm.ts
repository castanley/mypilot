import { writable } from "svelte/store";

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  // Require typing this exact string to enable the confirm button.
  typeToConfirm?: string;
}

interface ConfirmState extends ConfirmOptions {
  open: boolean;
  resolve: ((ok: boolean) => void) | null;
}

const initial: ConfirmState = {
  open: false,
  title: "",
  message: "",
  resolve: null,
};

export const confirmState = writable<ConfirmState>(initial);

export function confirmAction(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    confirmState.set({ ...initial, ...opts, open: true, resolve });
  });
}

export function resolveConfirm(ok: boolean) {
  confirmState.update((s) => {
    s.resolve?.(ok);
    return { ...initial };
  });
}
