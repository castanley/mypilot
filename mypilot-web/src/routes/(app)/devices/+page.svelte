<script lang="ts">
  import { base } from "$app/paths";
  import Button from "$lib/components/Button.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import Segmented from "$lib/components/Segmented.svelte";
  import Skeleton from "$lib/components/Skeleton.svelte";
  import StatusBadge from "$lib/components/StatusBadge.svelte";
  import { seedDevices, visibleDevices } from "$lib/stores/devices";
  import type { DeviceSummary } from "$lib/types";
  import { relTime, shortId } from "$lib/utils";

  // SSR-loaded initial data (see +page.server.ts) seeds the shared store synchronously (no flash),
  // then the store keeps every device live (presence/onroad/heartbeat) — no per-page WS handler.
  export let data: { devices: DeviceSummary[] };
  seedDevices(data.devices);

  const loading = false;
  let query = "";
  let filter: "all" | "online" | "onroad" = "all";

  // The store's visibleDevices already excludes revoked; apply the view filter + search on top.
  $: filtered = $visibleDevices
    .filter((d) => {
      if (filter === "online") return d.online;
      if (filter === "onroad") return d.onroad;
      return true;
    })
    .filter((d) => {
      if (!query) return true;
      const q = query.toLowerCase();
      return d.alias.toLowerCase().includes(q) || d.id.toLowerCase().includes(q);
    });
</script>

<svelte:head><title>Devices · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="Fleet"
  title="Devices"
  description="Every device paired to this control plane.">
  <svelte:fragment slot="actions">
    <Button variant="primary" icon="add-device" href={base + "/devices/pair"}>Pair device</Button>
  </svelte:fragment>
</PageHeader>

<div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
  <div class="relative max-w-xs flex-1">
    <Icon name="search" size={16} class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-subtle" />
    <input class="input pl-9" placeholder="Search by name or ID" bind:value={query} />
  </div>
  <Segmented
    bind:value={filter}
    options={[
      { value: "all", label: "All" },
      { value: "online", label: "Online" },
      { value: "onroad", label: "On road" },
    ]} />
</div>

{#if loading}
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
    {#each Array(3) as _}
      <div class="card panel-pad"><Skeleton height="6rem" /></div>
    {/each}
  </div>
{:else if filtered.length === 0}
  <div class="card">
    <EmptyState
      icon="devices"
      title={$visibleDevices.length === 0 ? "No devices paired" : "No matches"}
      description={$visibleDevices.length === 0
        ? "Pair your first device to start monitoring and configuring it."
        : "Try a different search or filter."}>
      {#if $visibleDevices.length === 0}
        <Button variant="primary" icon="add-device" href={base + "/devices/pair"}>Pair a device</Button>
      {/if}
    </EmptyState>
  </div>
{:else}
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
    {#each filtered as d (d.id)}
      <a
        href={base + "/devices/" + d.id}
        class="card group relative overflow-hidden p-5 transition hover:border-line-strong hover:shadow-md">
        <div class="flex items-start justify-between gap-3">
          <div class="grid h-11 w-11 place-items-center rounded-xl border border-line bg-surface-2 text-fg-muted">
            <Icon name="car" size={20} />
          </div>
          <StatusBadge online={d.online} onroad={d.onroad} size="sm" />
        </div>
        <h3 class="mt-4 flex items-center gap-2 truncate text-base font-semibold text-fg">
          {d.alias}
          {#if d.is_simulated}<span class="badge badge-warning shrink-0">SIM</span>{/if}
        </h3>
        <p class="mono mt-0.5 truncate text-xs text-fg-subtle">{shortId(d.id, 8, 6)}</p>
        <div class="mt-4 grid grid-cols-2 gap-3 border-t border-line pt-3.5 text-xs">
          <div>
            <p class="text-fg-subtle">Platform</p>
            <p class="mt-0.5 font-medium text-fg">{d.platform ?? "—"}</p>
          </div>
          <div>
            <p class="text-fg-subtle">Software</p>
            <p class="mt-0.5 truncate font-medium text-fg">{d.software_version ?? "—"}</p>
          </div>
          <div>
            <p class="text-fg-subtle">Branch</p>
            <p class="mt-0.5 truncate font-medium text-fg">{d.branch ?? "—"}</p>
          </div>
          <div>
            <p class="text-fg-subtle">Heartbeat</p>
            <p class="mt-0.5 font-medium text-fg">{relTime(d.last_heartbeat_at)}</p>
          </div>
        </div>
      </a>
    {/each}
  </div>
{/if}
