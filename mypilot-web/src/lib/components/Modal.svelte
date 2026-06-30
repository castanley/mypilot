<script lang="ts">
  import { browser } from "$app/environment";
  import { cx } from "$lib/utils";
  import { createEventDispatcher, onDestroy } from "svelte";
  import { fade, scale } from "svelte/transition";
  import Icon from "./Icon.svelte";

  export let open = false;
  export let title = "";
  export let size: "sm" | "md" | "lg" = "md";
  export let closeOnBackdrop = true;

  const dispatch = createEventDispatcher<{ close: void }>();

  let dialogEl: HTMLDivElement | null = null;
  let prevFocus: HTMLElement | null = null;

  function close() {
    dispatch("close");
  }

  function focusables(): HTMLElement[] {
    if (!dialogEl) return [];
    return Array.from(
      dialogEl.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => el.offsetParent !== null);
  }

  function onKey(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === "Escape") {
      close();
      return;
    }
    if (e.key === "Tab") {
      const items = focusables();
      if (items.length === 0) {
        e.preventDefault();
        dialogEl?.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (e.shiftKey && (active === first || !dialogEl?.contains(active))) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  $: if (browser) {
    document.body.style.overflow = open ? "hidden" : "";
  }

  $: if (browser && open && dialogEl) {
    prevFocus = document.activeElement as HTMLElement | null;
    const items = focusables();
    (items[0] ?? dialogEl).focus();
  }

  $: if (browser && !open && prevFocus) {
    prevFocus.focus();
    prevFocus = null;
  }

  onDestroy(() => {
    if (browser) {
      document.body.style.overflow = "";
      prevFocus?.focus();
    }
  });

  const sizes = { sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl" };
</script>

<svelte:window on:keydown={onKey} />

{#if open}
  <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
    <div
      class="absolute inset-0 bg-black/60 backdrop-blur-sm"
      transition:fade={{ duration: 150 }}
      on:click={() => closeOnBackdrop && close()}
      role="presentation"></div>
    <div
      bind:this={dialogEl}
      tabindex="-1"
      class={cx("card relative z-10 w-full overflow-hidden shadow-xl outline-none", sizes[size])}
      role="dialog"
      aria-modal="true"
      aria-label={title}
      transition:scale={{ duration: 160, start: 0.96, opacity: 0 }}>
      {#if title}
        <div class="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 class="text-base font-semibold text-fg">{title}</h2>
          <button
            type="button"
            class="btn btn-ghost btn-icon-sm -mr-1.5"
            aria-label="Close"
            on:click={close}>
            <Icon name="x" size={18} />
          </button>
        </div>
      {/if}
      <div class="px-5 py-4">
        <slot />
      </div>
      {#if $$slots.footer}
        <div class="flex items-center justify-end gap-2 border-t border-line bg-bg-subtle px-5 py-3.5">
          <slot name="footer" />
        </div>
      {/if}
    </div>
  </div>
{/if}
