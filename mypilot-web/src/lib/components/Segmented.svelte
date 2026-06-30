<script lang="ts">
  import { cx } from "$lib/utils";
  import { createEventDispatcher } from "svelte";

  type Opt = { value: unknown; label: string };
  export let options: Opt[] = [];
  export let value: unknown = undefined;
  export let disabled = false;
  export let size: "sm" | "md" = "md";

  const dispatch = createEventDispatcher<{ change: unknown }>();

  function select(v: unknown) {
    if (disabled || v === value) return;
    value = v;
    dispatch("change", v);
  }
</script>

<div
  role="radiogroup"
  class={cx(
    "inline-flex items-center gap-1 rounded-md border border-line bg-surface-2 p-1",
    disabled && "pointer-events-none opacity-50",
  )}>
  {#each options as opt (String(opt.value))}
    <button
      type="button"
      role="radio"
      aria-checked={opt.value === value}
      on:click={() => select(opt.value)}
      class={cx(
        "rounded font-medium transition-colors duration-150 ease-smooth focus-visible:outline-2 focus-visible:outline-offset-1",
        size === "sm" ? "px-2.5 py-1 text-[0.8125rem]" : "px-3 py-1.5 text-sm",
        opt.value === value
          ? "bg-surface text-fg shadow-sm ring-1 ring-line-strong"
          : "text-fg-muted hover:text-fg",
      )}>
      {opt.label}
    </button>
  {/each}
</div>
