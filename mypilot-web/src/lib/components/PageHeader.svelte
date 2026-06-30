<script lang="ts">
  export let title = "";
  export let description: string | null = null;
  export let eyebrow: string | null = null;
</script>

<div class="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
  <div class="min-w-0">
    {#if eyebrow}<p class="section-label mb-1.5">{eyebrow}</p>{/if}
    <h1 class="text-xl font-semibold tracking-tight text-fg sm:text-2xl">{title}</h1>
    {#if description}
      <p class="mt-1 max-w-2xl text-sm text-fg-muted">{description}</p>
    {/if}
  </div>
  {#if $$slots.actions}
    <!-- Wrap on small screens so multiple buttons don't overflow the viewport (they're
         whitespace-nowrap and were shrink-0, which forced horizontal scroll on phones). On >=sm the
         header is a row and actions stay on one line. -->
    <div class="flex flex-wrap items-center gap-2 sm:shrink-0">
      <slot name="actions" />
    </div>
  {/if}
</div>
