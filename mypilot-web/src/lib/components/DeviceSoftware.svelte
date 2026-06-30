<script lang="ts">
  import { ApiError, getDeviceSoftware, rollbackSoftware, updateSoftware } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import Card from "$lib/components/Card.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import Skeleton from "$lib/components/Skeleton.svelte";
  import { confirmAction } from "$lib/stores/confirm";
  import { subscribeRealtime } from "$lib/realtime";
  import { toast } from "$lib/stores/toast";
  import type { DeviceSoftwareState } from "$lib/types";
  import { onMount } from "svelte";

  export let deviceId: string;

  let data: DeviceSoftwareState | null = null;
  let loading = true;
  let busy = "";

  async function load() {
    try {
      data = await getDeviceSoftware(deviceId);
    } catch {
      toast.error("Failed to load software");
    } finally {
      loading = false;
    }
  }

  $: channels = data
    ? [...new Set(data.releases.map((r) => r.channel))]
    : [];

  async function doUpdate(version: string, channel: string) {
    if (data?.onroad) {
      toast.error("Device is onroad", "Software updates are only allowed while parked.");
      return;
    }
    const ok = await confirmAction({
      title: "Install update",
      message: `Update this device to ${version} (${channel})? The device installs while offroad and reboots into the new version.`,
      confirmLabel: "Install",
      danger: true,
    });
    if (!ok) return;
    busy = version;
    try {
      await updateSoftware(deviceId, version, true);
      toast.success("Update sent", "The device is downloading and installing.");
      setTimeout(load, 3500);
    } catch (e) {
      toast.error("Update failed", e instanceof ApiError ? e.message : undefined);
    } finally {
      busy = "";
    }
  }

  async function doRollback() {
    const ok = await confirmAction({
      title: "Roll back software",
      message: `Roll back to ${data?.previous_version}?`,
      confirmLabel: "Roll back",
    });
    if (!ok) return;
    busy = "__rb";
    try {
      await rollbackSoftware(deviceId);
      toast.success("Rollback sent");
      setTimeout(load, 3500);
    } catch (e) {
      toast.error("Rollback failed", e instanceof ApiError ? e.message : undefined);
    } finally {
      busy = "";
    }
  }

  onMount(() => {
    load();
    const unsub = subscribeRealtime((e) => {
      if (e.device_id !== deviceId) return;
      if (e.type === "device_event" && e.event === "command_result") load();
      if (e.type === "device_status") load();
    });
    return () => unsub();
  });
</script>

{#if loading}
  <Skeleton height="18rem" />
{:else if data}
  <Card title="Current software" icon="software">
    <svelte:fragment slot="actions">
      {#if data.previous_version}
        <Button variant="secondary" size="sm" icon="refresh-cw" loading={busy === "__rb"} on:click={doRollback}>
          Roll back
        </Button>
      {/if}
    </svelte:fragment>
    <div class="grid grid-cols-2 gap-4 sm:grid-cols-3">
      <div>
        <p class="text-xs text-fg-subtle">Version</p>
        <p class="mt-0.5 font-semibold text-fg">{data.current_version ?? "—"}</p>
      </div>
      <div>
        <p class="text-xs text-fg-subtle">Branch</p>
        <p class="mt-0.5 font-medium text-fg">{data.current_branch ?? "—"}</p>
      </div>
      <div>
        <p class="text-xs text-fg-subtle">Channel</p>
        <p class="mt-0.5 font-medium capitalize text-fg">{data.update_channel ?? "—"}</p>
      </div>
    </div>
    {#if data.update_state && data.update_state !== "idle"}
      <div class="mt-4 flex items-center gap-2.5 rounded-lg border border-info/40 bg-info-soft px-4 py-2.5 text-sm">
        <Icon name="refresh-cw" size={16} class="shrink-0 animate-spin text-info" />
        <span class="text-fg-muted capitalize">{data.update_state} {data.target_version ?? ""}…</span>
      </div>
    {/if}
  </Card>

  {#each channels as ch}
    <div class="mt-5">
      <p class="section-label mb-2 capitalize">{ch} channel</p>
      <div class="card divide-y divide-line">
        {#each data.releases.filter((r) => r.channel === ch) as r (r.id)}
          <div class="flex items-center justify-between gap-3 p-4">
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <p class="font-medium text-fg">{r.version}</p>
                {#if r.version === data.current_version}
                  <span class="badge badge-success"><Icon name="check" size={12} /> Installed</span>
                {:else if r.is_current}
                  <span class="badge badge-accent">Latest</span>
                {/if}
              </div>
              <p class="mt-0.5 line-clamp-1 text-xs text-fg-muted">{r.notes}</p>
            </div>
            {#if r.version === data.current_version}
              <span class="text-xs text-fg-subtle">Running</span>
            {:else}
              <Button
                variant="secondary"
                size="sm"
                loading={busy === r.version}
                disabled={data.onroad || !!busy}
                on:click={() => doUpdate(r.version, r.channel)}>
                Install
              </Button>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {/each}
{/if}
