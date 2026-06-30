<script lang="ts">
  import { dismissToast, toasts, type ToastKind } from "$lib/stores/toast";
  import { flip } from "svelte/animate";
  import { fly } from "svelte/transition";
  import Icon from "./Icon.svelte";

  const meta: Record<ToastKind, { icon: string; cls: string }> = {
    success: { icon: "check", cls: "text-success border-success/40" },
    error: { icon: "alert-triangle", cls: "text-danger border-danger/40" },
    warning: { icon: "alert-triangle", cls: "text-warning border-warning/40" },
    info: { icon: "info", cls: "text-info border-info/40" },
  };
</script>

<div
  class="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[calc(100vw-2rem)] max-w-sm flex-col gap-2.5"
  aria-live="polite">
  {#each $toasts as t (t.id)}
    <div
      animate:flip={{ duration: 200 }}
      in:fly={{ y: 16, duration: 220 }}
      out:fly={{ x: 24, duration: 180 }}
      class="card pointer-events-auto flex items-start gap-3 p-3.5 shadow-xl">
      <div class="grid h-7 w-7 shrink-0 place-items-center rounded-lg border bg-surface-2 {meta[t.kind].cls}">
        <Icon name={meta[t.kind].icon} size={15} />
      </div>
      <div class="min-w-0 flex-1 pt-0.5">
        <p class="text-sm font-medium text-fg">{t.title}</p>
        {#if t.description}
          <p class="mt-0.5 text-xs text-fg-muted">{t.description}</p>
        {/if}
      </div>
      <button
        type="button"
        class="btn btn-ghost btn-icon-sm -mr-1 -mt-1"
        aria-label="Dismiss"
        on:click={() => dismissToast(t.id)}>
        <Icon name="x" size={15} />
      </button>
    </div>
  {/each}
</div>
