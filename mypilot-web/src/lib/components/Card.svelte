<script lang="ts">
  import { cx } from "$lib/utils";
  import Icon from "./Icon.svelte";
  export let title: string | null = null;
  export let subtitle: string | null = null;
  export let icon: string | null = null;
  export let pad = true;
  let className = "";
  export { className as class };
</script>

<section class={cx("card", className)}>
  {#if title || $$slots.header || $$slots.actions}
    <header class="flex items-start justify-between gap-3 border-b border-line px-4 py-3.5 sm:px-5">
      <div class="flex items-start gap-3">
        {#if icon}
          <div class="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-accent">
            <Icon name={icon} size={16} />
          </div>
        {/if}
        <div>
          {#if title}<h3 class="text-sm font-semibold text-fg">{title}</h3>{/if}
          {#if subtitle}<p class="mt-0.5 text-xs text-fg-muted">{subtitle}</p>{/if}
          <slot name="header" />
        </div>
      </div>
      <slot name="actions" />
    </header>
  {/if}
  <div class={cx(pad && "panel-pad")}>
    <slot />
  </div>
</section>
