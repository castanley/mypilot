<script lang="ts">
  import { cx } from "$lib/utils";
  import { createEventDispatcher } from "svelte";

  export let value = 0;
  export let min = 0;
  export let max = 100;
  export let step = 1;
  export let disabled = false;
  export let unit = "";

  const dispatch = createEventDispatcher<{ change: number; input: number }>();
  $: pct = max === min ? 0 : ((value - min) / (max - min)) * 100;

  function onInput(e: Event) {
    value = Number((e.target as HTMLInputElement).value);
    dispatch("input", value);
  }
  function onChange() {
    dispatch("change", value);
  }
</script>

<div class={cx("flex items-center gap-3", disabled && "opacity-50")}>
  <div class="relative flex-1">
    <div class="pointer-events-none absolute inset-y-0 left-0 my-auto h-1.5 w-full rounded-full bg-surface-3"></div>
    <div
      class="pointer-events-none absolute inset-y-0 left-0 my-auto h-1.5 rounded-full bg-accent"
      style="width: {pct}%"></div>
    <input
      type="range"
      {min}
      {max}
      {step}
      {disabled}
      bind:value
      on:input={onInput}
      on:change={onChange}
      class="slider-input relative h-6 w-full cursor-pointer appearance-none bg-transparent" />
  </div>
  <div class="w-16 shrink-0 text-right mono text-sm font-medium text-fg">
    {value}{#if unit}<span class="text-xs text-fg-subtle">{unit}</span>{/if}
  </div>
</div>

<style>
  .slider-input::-webkit-slider-thumb {
    -webkit-appearance: none;
    height: 18px;
    width: 18px;
    border-radius: 999px;
    background: rgb(var(--surface));
    border: 2px solid rgb(var(--accent));
    box-shadow: 0 1px 4px rgb(0 0 0 / 0.35);
    cursor: pointer;
    margin-top: 0;
  }
  .slider-input::-moz-range-thumb {
    height: 18px;
    width: 18px;
    border-radius: 999px;
    background: rgb(var(--surface));
    border: 2px solid rgb(var(--accent));
    cursor: pointer;
  }
  .slider-input:focus-visible::-webkit-slider-thumb {
    outline: 2px solid rgb(var(--accent));
    outline-offset: 2px;
  }
</style>
