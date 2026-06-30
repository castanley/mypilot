<script lang="ts">
  import { cx } from "$lib/utils";
  import { createEventDispatcher } from "svelte";
  import Icon from "./Icon.svelte";

  type Opt = { value: unknown; label: string };
  export let options: Opt[] = [];
  export let value: unknown = undefined;
  export let disabled = false;
  export let id: string | undefined = undefined;
  export let invalid = false;

  const dispatch = createEventDispatcher<{ change: unknown }>();

  function onChange(e: Event) {
    const idx = (e.target as HTMLSelectElement).selectedIndex;
    value = options[idx]?.value;
    dispatch("change", value);
  }
  $: selectedIndex = options.findIndex((o) => String(o.value) === String(value));
</script>

<div class="relative inline-block w-full">
  <select
    {id}
    {disabled}
    on:change={onChange}
    class={cx("input cursor-pointer appearance-none pr-9", invalid && "input-invalid")}>
    {#each options as opt, i (String(opt.value))}
      <option value={String(opt.value)} selected={i === selectedIndex}>{opt.label}</option>
    {/each}
  </select>
  <Icon
    name="chevron-down"
    size={16}
    class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
</div>
