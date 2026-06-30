<script lang="ts">
  import { base } from "$app/paths";
  import { goto } from "$app/navigation";
  import { getRoutes } from "$lib/api";
  import Card from "$lib/components/Card.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import Select from "$lib/components/Select.svelte";
  import { subscribeDeviceEvents } from "$lib/realtime";
  import type { DeviceSummary, RouteSummary } from "$lib/types";
  import { clockTime, dayLabel, fmtDistance, fmtDuration } from "$lib/utils";
  import { onMount } from "svelte";

  export let data: { devices: DeviceSummary[]; selected: string; routes: RouteSummary[] };

  let selected = data.selected;
  let routes = data.routes;
  let loading = false;

  $: deviceOptions = data.devices.map((d) => ({ value: d.id, label: d.alias }));

  // Group drives by day (newest first), preserving each day's drives in time order.
  $: groups = (() => {
    const byDay = new Map<string, RouteSummary[]>();
    for (const r of [...routes].sort(
      (a, b) =>
        new Date(b.started_at ?? b.created_at).getTime() -
        new Date(a.started_at ?? a.created_at).getTime(),
    )) {
      const key = dayLabel(r.started_at ?? r.created_at);
      (byDay.get(key) ?? byDay.set(key, []).get(key)!).push(r);
    }
    return [...byDay.entries()];
  })();

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
    goto(`${base}/drives?device=${id}`, { replaceState: true, noScroll: true, keepFocus: true });
    await loadRoutes(id);
  }

  onMount(() =>
    subscribeDeviceEvents((e) => {
      if (e.event === "route_uploaded" && selected) loadRoutes(selected);
    }),
  );
</script>

<svelte:head><title>Drives · MyPilot</title></svelte:head>

<PageHeader eyebrow="Fleet" title="Drives" description="Recorded drive video from your devices.">
  <svelte:fragment slot="actions">
    {#if deviceOptions.length}
      <Select value={selected} options={deviceOptions} on:change={(e) => onDeviceChange(String(e.detail))} />
    {/if}
  </svelte:fragment>
</PageHeader>

{#if !selected}
  <EmptyState icon="devices" title="No devices" description="Pair a device to see its drives." />
{:else if routes.length === 0}
  <EmptyState
    icon="video"
    title="No drives yet"
    description="Drives appear here once the device uploads them. Enable drive upload in the device's settings." />
{:else}
  <div class="space-y-8">
    {#each groups as [day, items]}
      <section>
        <h2 class="section-label mb-3">{day}</h2>
        <Card>
          <ul class="-my-1 divide-y divide-line">
            {#each items as r (r.id)}
              <li>
                <a
                  href={base + "/drives/" + r.id}
                  class="group flex items-center gap-4 rounded-lg px-2 py-3 transition hover:bg-surface-2">
                  <div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-fg-muted group-hover:text-accent">
                    <Icon name="play" size={16} />
                  </div>
                  <div class="min-w-0 flex-1">
                    <p class="truncate text-sm font-medium text-fg">{clockTime(r.started_at ?? r.created_at)}</p>
                    <p class="mono truncate text-xs text-fg-subtle">{r.name}</p>
                  </div>
                  <div class="hidden shrink-0 text-right text-xs text-fg-muted sm:block">
                    <p>{fmtDuration(r.duration_s)} · {fmtDistance(r.distance_m)}</p>
                    <p class="text-fg-subtle">{r.segment_count} seg</p>
                  </div>
                  <Icon name="chevron-right" size={16} class="hidden shrink-0 text-fg-subtle group-hover:text-fg-muted sm:block" />
                </a>
              </li>
            {/each}
          </ul>
        </Card>
      </section>
    {/each}
  </div>
{/if}
