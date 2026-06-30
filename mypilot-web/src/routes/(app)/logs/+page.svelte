<script lang="ts">
  import { base } from "$app/paths";
  import { goto } from "$app/navigation";
  import { ApiError, deleteLog, getLogs, logDownloadUrl } from "$lib/api";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import Segmented from "$lib/components/Segmented.svelte";
  import Select from "$lib/components/Select.svelte";
  import { confirmAction } from "$lib/stores/confirm";
  import { toast } from "$lib/stores/toast";
  import { subscribeDeviceEvents } from "$lib/realtime";
  import type { DeviceSummary, LogOut } from "$lib/types";
  import { fmtBytes, relTime } from "$lib/utils";
  import { onMount } from "svelte";

  export let data: { devices: DeviceSummary[]; selected: string; logs: LogOut[] };

  let selected = data.selected;
  let logs = data.logs;
  let kind: "all" | "system" | "crash" = "all";
  let loading = false;

  $: deviceOptions = data.devices.map((d) => ({ value: d.id, label: d.alias }));
  $: filtered = kind === "all" ? logs : logs.filter((l) => l.kind === kind);

  async function loadLogs(deviceId: string) {
    if (!deviceId) {
      logs = [];
      return;
    }
    loading = true;
    try {
      logs = await getLogs(deviceId);
    } finally {
      loading = false;
    }
  }

  async function onDeviceChange(id: string) {
    selected = id;
    goto(`${base}/logs?device=${id}`, { replaceState: true, noScroll: true, keepFocus: true });
    await loadLogs(id);
  }

  async function doDelete(log: LogOut) {
    const ok = await confirmAction({
      title: "Delete log",
      message: `Permanently delete ${log.name} from storage?`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteLog(log.id);
      logs = logs.filter((l) => l.id !== log.id);
      toast.success("Log deleted");
    } catch (e) {
      toast.error("Delete failed", e instanceof ApiError ? e.message : undefined);
    }
  }

  function kindBadge(k: string): string {
    if (k === "crash") return "badge-danger";
    if (k === "system") return "badge-info";
    return "badge-neutral";
  }

  onMount(() => {
    const unsub = subscribeDeviceEvents((e) => {
      if (e.device_id === selected && e.event === "log_uploaded") loadLogs(selected);
    });
    return () => unsub();
  });
</script>

<svelte:head><title>Logs · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="System"
  title="Logs"
  description="Crash and system logs your devices have uploaded — stored on infrastructure you control.">
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
      description="Pair a device to start collecting logs.">
      <a class="btn btn-primary btn-md" href={base + "/devices/pair"}>Pair a device</a>
    </EmptyState>
  </div>
{:else}
  <div class="mb-4">
    <Segmented
      bind:value={kind}
      options={[
        { value: "all", label: "All" },
        { value: "system", label: "System" },
        { value: "crash", label: "Crash" },
      ]} />
  </div>

  {#if loading}
    <div class="card panel-pad"><div class="skeleton h-64 w-full"></div></div>
  {:else if filtered.length === 0}
    <div class="card">
      <EmptyState
        icon="logs"
        title="No logs"
        description="Logs uploaded by this device will appear here." />
    </div>
  {:else}
    <div class="card overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-line text-left text-xs text-fg-subtle">
              <th class="px-4 py-3 font-medium">Name</th>
              <th class="px-4 py-3 font-medium">Kind</th>
              <th class="px-4 py-3 font-medium">Drive</th>
              <th class="px-4 py-3 font-medium">Size</th>
              <th class="px-4 py-3 font-medium">Uploaded</th>
              <th class="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {#each filtered as l (l.id)}
              <tr class="border-b border-line/60 transition last:border-0 hover:bg-surface-2">
                <td class="px-4 py-3 mono text-fg">{l.name}</td>
                <td class="px-4 py-3"><span class="badge {kindBadge(l.kind)} capitalize">{l.kind}</span></td>
                <td class="px-4 py-3 mono text-xs text-fg-subtle">{l.route_name ?? "—"}</td>
                <td class="px-4 py-3 text-fg-muted">{fmtBytes(l.size_bytes)}</td>
                <td class="px-4 py-3 text-fg-muted">{relTime(l.created_at)}</td>
                <td class="px-4 py-3">
                  <div class="flex items-center justify-end gap-2">
                    {#if l.upload_status === "complete"}
                      <a class="btn btn-secondary btn-sm" href={logDownloadUrl(l.id)} download={l.name}>
                        <Icon name="download" size={15} /> Download
                      </a>
                    {:else}
                      <span class="badge badge-warning">Uploading</span>
                    {/if}
                    <button
                      type="button"
                      class="btn btn-ghost btn-icon-sm"
                      aria-label="Delete log"
                      on:click={() => doDelete(l)}>
                      <Icon name="trash" size={15} />
                    </button>
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
{/if}
