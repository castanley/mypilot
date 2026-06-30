<script lang="ts">
  import { base } from "$app/paths";
  import {
    createSimDevice,
    deleteSimDevice,
    listSimDevices,
    replayDrive,
    stopReplay,
  } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import Card from "$lib/components/Card.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import { seedDevices, devices as deviceMap } from "$lib/stores/devices";
  import { toast } from "$lib/stores/toast";
  import type { DeviceSummary, RouteSummary } from "$lib/types";
  import { fmtDistance, fmtDuration, shortId } from "$lib/utils";

  export let data: { sims: DeviceSummary[]; routes: RouteSummary[] };

  let sims = data.sims;
  $: routes = data.routes;
  // Seed the sim devices into the shared store so their live `replaying` flag tracks the WS feed
  // (the store owns the one subscription). Re-seed whenever the admin list refreshes.
  $: seedDevices(sims);
  // Live "is replaying" per device, read straight from the store node (kept current by the WS).
  $: replaying = Object.fromEntries(sims.map((s) => [s.id, $deviceMap[s.id]?.replaying ?? false]));

  let busy = false;
  let newAlias = "Simulated test device";
  let routeFor: Record<string, string> = {};
  let speedFactor = 4;

  async function refresh() {
    sims = await listSimDevices();
  }

  async function addSim() {
    if (!newAlias.trim()) return;
    busy = true;
    try {
      await createSimDevice(newAlias.trim());
      toast.success("Sim device created");
      await refresh();
    } catch {
      toast.error("Couldn't create sim device");
    } finally {
      busy = false;
    }
  }

  async function removeSim(id: string) {
    busy = true;
    try {
      await deleteSimDevice(id);
      toast.success("Sim device removed");
      await refresh();
    } catch {
      toast.error("Couldn't remove sim device");
    } finally {
      busy = false;
    }
  }

  async function startReplay(id: string) {
    const routeId = routeFor[id] || routes[0]?.id;
    if (!routeId) {
      toast.error("No route with a GPS track to replay");
      return;
    }
    try {
      const r = await replayDrive(id, routeId, speedFactor);
      toast.success("Replay started", `${r.points} points`);
    } catch {
      toast.error("Couldn't start replay");
    }
  }

  async function endReplay(id: string) {
    try {
      await stopReplay(id);
      toast.success("Replay stopped");
    } catch {
      toast.error("Couldn't stop replay");
    }
  }

  const routeLabel = (r: RouteSummary) =>
    `${r.alias ?? r.name}${r.distance_m ? " · " + fmtDistance(r.distance_m) : ""}${r.duration_s ? " · " + fmtDuration(r.duration_s) : ""}`;
  // `replaying` is derived from the shared store above — no per-page WS handler needed.
</script>

<svelte:head><title>Developer · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="Admin"
  title="Developer tools"
  description="Create simulated test devices and replay recorded drives through them — exercise live telemetry without driving." />

<Card title="Simulated devices" subtitle="Test fixtures — never real hardware" icon="developer" class="mt-2">
  <!-- Create form: stacks on mobile (input full-width), inline on >=sm. -->
  <div class="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center">
    <input class="input h-9 sm:max-w-xs" bind:value={newAlias} placeholder="New sim device alias" />
    <Button variant="primary" size="sm" icon="add-device" loading={busy} on:click={addSim}>
      Add sim device
    </Button>
  </div>

  {#if sims.length === 0}
    <EmptyState
      icon="developer"
      title="No simulated devices"
      description="Add one, then replay a recorded drive through it to see live speed, heading, and position on the dashboard and device page." />
  {:else}
    <div class="mb-4 flex items-center gap-3">
      <label class="text-sm text-fg-muted" for="sf">Replay speed</label>
      <select id="sf" class="input h-9 w-28" bind:value={speedFactor}>
        <option value={1}>1× (real)</option>
        <option value={4}>4×</option>
        <option value={10}>10×</option>
        <option value={30}>30×</option>
      </select>
    </div>
    <ul class="divide-y divide-line">
      {#each sims as d (d.id)}
        <li class="flex flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <a href={base + "/devices/" + d.id} class="truncate text-sm font-medium text-fg hover:text-accent">{d.alias}</a>
              <span class="badge badge-warning shrink-0">SIM</span>
              {#if replaying[d.id]}
                <span class="badge badge-accent shrink-0"><span class="dot bg-accent"></span> Replaying</span>
              {/if}
            </div>
            <p class="mono truncate text-xs text-fg-subtle">{shortId(d.id)}</p>
          </div>
          <!-- Controls: full-width select that wraps above the buttons on mobile; inline on >=sm. -->
          <div class="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
            <select class="input h-9 w-full min-w-0 sm:w-56" bind:value={routeFor[d.id]} disabled={routes.length === 0}>
              {#each routes as r (r.id)}
                <option value={r.id}>{routeLabel(r)}</option>
              {/each}
            </select>
            <div class="flex items-center gap-2">
              {#if replaying[d.id]}
                <Button variant="secondary" size="sm" icon="x" on:click={() => endReplay(d.id)}>Stop</Button>
              {:else}
                <Button variant="primary" size="sm" icon="play" disabled={routes.length === 0} on:click={() => startReplay(d.id)}>Replay</Button>
              {/if}
              <Button variant="ghost" size="sm" icon="trash" on:click={() => removeSim(d.id)}>Remove</Button>
            </div>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</Card>
