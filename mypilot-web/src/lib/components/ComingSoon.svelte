<script lang="ts">
  import Icon from "./Icon.svelte";
  export let icon = "sparkles";
  export let title = "Coming soon";
  export let description = "This area is on the roadmap.";
  export let bullets: string[] = [];
</script>

<div class="mx-auto flex max-w-xl flex-col items-center gap-5 px-6 py-16 text-center">
  <div class="grid h-16 w-16 place-items-center rounded-2xl border border-line bg-surface-2 text-accent">
    <Icon name={icon} size={28} />
  </div>
  <div class="space-y-2">
    <span class="badge badge-accent">Coming soon</span>
    <h1 class="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
    <p class="text-sm text-fg-muted">{description}</p>
  </div>
  {#if bullets.length}
    <ul class="w-full space-y-2 text-left">
      {#each bullets as b}
        <li class="flex items-start gap-2.5 rounded-lg border border-line bg-surface px-4 py-3 text-sm text-fg-muted">
          <Icon name="check" size={16} class="mt-0.5 shrink-0 text-success" />
          <span>{b}</span>
        </li>
      {/each}
    </ul>
  {/if}
</div>
