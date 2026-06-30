<script lang="ts">
  import { cx } from "$lib/utils";
  import { createEventDispatcher } from "svelte";

  export let checked = false;
  export let disabled = false;
  export let id: string | undefined = undefined;
  export let ariaLabel: string | undefined = undefined;

  const dispatch = createEventDispatcher<{ change: boolean }>();

  function toggle() {
    if (disabled) return;
    checked = !checked;
    dispatch("change", checked);
  }
</script>

<button
  {id}
  type="button"
  role="switch"
  aria-checked={checked}
  aria-label={ariaLabel}
  {disabled}
  on:click={toggle}
  class={cx(
    "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors duration-200 ease-smooth focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
    checked ? "border-accent bg-accent" : "border-line-strong bg-surface-3",
  )}>
  <span
    class={cx(
      "pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform duration-200 ease-smooth",
      checked ? "translate-x-6" : "translate-x-1",
    )}></span>
</button>
