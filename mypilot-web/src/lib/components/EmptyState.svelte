<script lang="ts">
  import Icon from "./Icon.svelte";
  export let icon = "info";
  export let title = "";
  export let description = "";
</script>

<div class="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
  <div class="grid h-12 w-12 place-items-center rounded-xl border border-line bg-surface-2 text-fg-subtle">
    <Icon name={icon} size={22} />
  </div>
  <div class="space-y-1">
    <p class="text-sm font-semibold text-fg">{title}</p>
    {#if description}
      <p class="mx-auto max-w-sm text-sm text-fg-muted">{description}</p>
    {/if}
  </div>
  {#if $$slots.default}
    <div class="mt-1"><slot /></div>
  {/if}
</div>
