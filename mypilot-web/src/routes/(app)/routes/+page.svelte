<script lang="ts">
  import { base } from "$app/paths";
  import { goto } from "$app/navigation";
  import { getRoutes } from "$lib/api";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import Select from "$lib/components/Select.svelte";
  import { subscribeDeviceEvents } from "$lib/realtime";
  import type { DeviceSummary, RouteSummary } from "$lib/types";
  import { fmtBytes, fmtDistance, fmtDuration, relTime } from "$lib/utils";
  import { onMount } from "svelte";

  export let data: { devices: DeviceSummary[]; selected: string; routes: RouteSummary[] };

  let selected = data.selected;
  let routes = data.routes;
  let loading = false;

  $: deviceOptions = data.devices.map((d) => ({ value: d.id, label: d.alias }));

  async function loadRoutes(deviceId: string) {
    if (!deviceId) {
      routes = [];
      return;
    }
    loading = true;
    try {
      routes = await getRoutes(deviceId);
    } finally {
      loading = false;
    }
  }

  async function onDeviceChange(id: string) {
    selected = id;
    // Keep the URL shareable/refresh-stable without a full navigation.
    goto(`${base}/routes?device=${id}`, { replaceState: true, noScroll: true, keepFocus: true });
    await loadRoutes(id);
  }

  function statusBadge(s: string): string {
    if (s === "complete") return "badge-success";
    if (s === "failed") return "badge-danger";
    return "badge-warning";
  }

  onMount(() => {
    const unsub = subscribeDeviceEvents((e) => {
      if (e.device_id === selected && e.event === "route_uploaded") loadRoutes(selected);
    });
    return () => unsub();
  });
</script>

<svelte:head><title>Routes · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="Fleet"
  title="Routes"
  description="Every drive your devices have uploaded, with segment logs you fully own.">
  <svelte:fragment slot="actions">
    {#if data.devices.length > 1}
      <div class="w-56">
        <Select
          value={selected}
          options={deviceOptions}
          on:change={(e) => onDeviceChange(String(e.detail))} />
      </div>
    {/if}
  </svelte:fragment>
</PageHeader>

{#if data.devices.length === 0}
  <div class="card">
    <EmptyState
      icon="devices"
      title="No devices paired"
      description="Pair a device to start recording and uploading drives.">
      <a class="btn btn-primary btn-md" href={base + "/devices/pair"}>Pair a device</a>
    </EmptyState>
  </div>
{:else if loading}
  <div class="card panel-pad"><div class="skeleton h-64 w-full"></div></div>
{:else if routes.length === 0}
  <div class="card">
    <EmptyState
      icon="routes"
      title="No drives yet"
      description="When this device finishes a drive and uploads it, the route will appear here." />
  </div>
{:else}
  <div class="card overflow-hidden">
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-line text-left text-xs text-fg-subtle">
            <th class="px-4 py-3 font-medium">Drive</th>
            <th class="px-4 py-3 font-medium">Recorded</th>
            <th class="px-4 py-3 font-medium">Duration</th>
            <th class="px-4 py-3 font-medium">Distance</th>
            <th class="px-4 py-3 font-medium">Segments</th>
            <th class="px-4 py-3 font-medium">Size</th>
            <th class="px-4 py-3 font-medium">Status</th>
            <th class="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody>
          {#each routes as r (r.id)}
            <tr
              class="cursor-pointer border-b border-line/60 transition last:border-0 hover:bg-surface-2"
              on:click={() => goto(`${base}/routes/${r.id}`)}>
              <td class="px-4 py-3">
                <div class="font-medium text-fg">{r.alias ?? r.name}</div>
                <div class="mono text-xs text-fg-subtle">{r.name}</div>
              </td>
              <td class="px-4 py-3 text-fg-muted">{relTime(r.started_at ?? r.created_at)}</td>
              <td class="px-4 py-3 text-fg-muted">{fmtDuration(r.duration_s)}</td>
              <td class="px-4 py-3 text-fg-muted">{fmtDistance(r.distance_m)}</td>
              <td class="px-4 py-3 text-fg-muted">{r.segment_count}</td>
              <td class="px-4 py-3 text-fg-muted">{fmtBytes(r.size_bytes)}</td>
              <td class="px-4 py-3">
                <span class="badge {statusBadge(r.upload_status)} capitalize">{r.upload_status}</span>
              </td>
              <td class="px-4 py-3 text-right">
                <Icon name="chevron-right" size={16} class="text-fg-subtle" />
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
{/if}
