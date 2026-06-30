<script lang="ts">
  import EmptyState from "$lib/components/EmptyState.svelte";
  import RouteTile from "$lib/components/RouteTile.svelte";
  import type { RouteSummary } from "$lib/types";

  export let data: { items: RouteSummary[] };
  // Only drives that actually have a GPS track get a tile (the loader already filters has_track=true).
  $: items = data.items;
</script>

<svelte:head><title>Map · MyPilot</title></svelte:head>

<div class="mx-auto max-w-6xl">
  <div class="mb-6">
    <h1 class="text-xl font-semibold tracking-tight text-fg sm:text-2xl">Drive map</h1>
    <p class="mt-1 text-sm text-fg-subtle">Each tile is a drive — click to open it.</p>
  </div>

  {#if items.length === 0}
    <EmptyState
      icon="map-pin"
      title="No mapped drives yet"
      description="Drives uploaded with GPS will appear here. Enable drive upload on the device and take a drive." />
  {:else}
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {#each items as route (route.id)}
        <RouteTile {route} />
      {/each}
    </div>
    <p class="mt-4 text-sm text-fg-subtle">{items.length} drive{items.length === 1 ? "" : "s"}.</p>
  {/if}
</div>
