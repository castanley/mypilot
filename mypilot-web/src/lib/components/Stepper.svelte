<script lang="ts">
  import { cx } from "$lib/utils";
  import { createEventDispatcher } from "svelte";
  import Icon from "./Icon.svelte";

  export let value = 0;
  export let min = 0;
  export let max = 100;
  export let step = 1;
  export let disabled = false;
  export let unit = "";

  const dispatch = createEventDispatcher<{ change: number }>();

  function decimals(s: number): number {
    const str = String(s);
    return str.includes(".") ? str.split(".")[1].length : 0;
  }
  $: fixed = decimals(step);
  function round(v: number): number {
    return Number(v.toFixed(fixed));
  }
  function set(v: number) {
    const clamped = round(Math.max(min, Math.min(max, v)));
    if (clamped === value) return;
    value = clamped;
    dispatch("change", value);
  }
</script>

<div
  class={cx(
    "inline-flex h-10 items-stretch overflow-hidden rounded-md border border-line-strong bg-surface-2",
    disabled && "pointer-events-none opacity-50",
  )}>
  <button
    type="button"
    aria-label="Decrease"
    on:click={() => set(value - step)}
    disabled={value <= min}
    class="grid w-9 place-items-center text-fg-muted transition hover:bg-surface-3 hover:text-fg disabled:opacity-40">
    <Icon name="minus" size={15} />
  </button>
  <div class="flex min-w-[4.5rem] items-center justify-center gap-1 border-x border-line px-2 mono text-sm font-medium text-fg">
    {value}{#if unit}<span class="text-xs text-fg-subtle">{unit}</span>{/if}
  </div>
  <button
    type="button"
    aria-label="Increase"
    on:click={() => set(value + step)}
    disabled={value >= max}
    class="grid w-9 place-items-center text-fg-muted transition hover:bg-surface-3 hover:text-fg disabled:opacity-40">
    <Icon name="plus" size={15} />
  </button>
</div>
