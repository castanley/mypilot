<script lang="ts">
  import { cx } from "$lib/utils";
  import Icon from "./Icon.svelte";

  export let label = "";
  export let value: string | number = "";
  export let icon = "activity";
  export let tone: "neutral" | "success" | "warning" | "danger" | "accent" = "neutral";
  export let hint: string | null = null;

  const tones: Record<string, string> = {
    neutral: "text-fg-muted",
    success: "text-success",
    warning: "text-warning",
    danger: "text-danger",
    accent: "text-accent",
  };
</script>

<div class="card panel-pad">
  <div class="flex items-center justify-between">
    <p class="text-sm font-medium text-fg-muted">{label}</p>
    <div class={cx("grid h-8 w-8 place-items-center rounded-lg border border-line bg-surface-2", tones[tone])}>
      <Icon name={icon} size={16} />
    </div>
  </div>
  <p class="mt-3 text-2xl font-semibold tracking-tight text-fg">{value}</p>
  {#if hint}<p class="mt-1 text-xs text-fg-subtle">{hint}</p>{/if}
</div>
