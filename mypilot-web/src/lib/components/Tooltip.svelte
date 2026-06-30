<script lang="ts">
  import { cx } from "$lib/utils";
  export let text = "";
  export let placement: "top" | "bottom" | "left" | "right" = "top";
  let open = false;

  const pos: Record<string, string> = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
    left: "right-full top-1/2 -translate-y-1/2 mr-2",
    right: "left-full top-1/2 -translate-y-1/2 ml-2",
  };
</script>

<span
  class="relative inline-flex"
  on:mouseenter={() => (open = true)}
  on:mouseleave={() => (open = false)}
  on:focusin={() => (open = true)}
  on:focusout={() => (open = false)}
  role="presentation">
  <slot />
  {#if open && text}
    <span
      role="tooltip"
      class={cx(
        "pointer-events-none absolute z-50 whitespace-nowrap rounded-md border border-line-strong bg-surface-3 px-2.5 py-1.5 text-xs font-medium text-fg shadow-lg",
        pos[placement],
      )}>
      {text}
    </span>
  {/if}
</span>
