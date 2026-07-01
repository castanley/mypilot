<script lang="ts">
  import { ApiError, getDeviceModels, rollbackModel, switchModel } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import Card from "$lib/components/Card.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import Skeleton from "$lib/components/Skeleton.svelte";
  import { confirmAction } from "$lib/stores/confirm";
  import { subscribeRealtime } from "$lib/realtime";
  import { toast } from "$lib/stores/toast";
  import type { DeviceModelsResponse } from "$lib/types";
  import { fmtBytes } from "$lib/utils";
  import { onMount } from "svelte";

  export let deviceId: string;

  let data: DeviceModelsResponse | null = null;
  let loading = true;
  let busy = "";

  async function load() {
    try {
      data = await getDeviceModels(deviceId);
    } catch {
      toast.error("Failed to load models");
    } finally {
      loading = false;
    }
  }

  $: active = data?.models.find((m) => m.active) ?? null;
  $: canRollback = !!data && data.models.some((m) => m.active) && data.models.length > 1;

  async function doSwitch(key: string, name: string, isDefault: boolean) {
    if (data?.onroad) {
      toast.error("Device is onroad", "Model switching is only allowed while parked.");
      return;
    }
    if (!isDefault) {
      const ok = await confirmAction({
        title: "Switch driving model",
        message: `Switch this device to "${name}"? The device verifies the model checksum, then activates it. Only applied while offroad.`,
        confirmLabel: "Switch model",
        danger: true,
      });
      if (!ok) return;
    }
    busy = key;
    try {
      await switchModel(deviceId, key, true);
      toast.success("Model switch sent", "The device is verifying and applying the model.");
      setTimeout(load, 3500);
    } catch (e) {
      toast.error("Switch failed", e instanceof ApiError ? e.message : undefined);
    } finally {
      busy = "";
    }
  }

  async function doRollback() {
    const ok = await confirmAction({
      title: "Roll back model",
      message: "Roll back to the previously active driving model?",
      confirmLabel: "Roll back",
    });
    if (!ok) return;
    busy = "__rollback";
    try {
      await rollbackModel(deviceId);
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
    });
    return () => unsub();
  });
</script>

{#if loading}
  <Skeleton height="18rem" />
{:else if data}
  {#if data.onroad}
    <div class="mb-4 flex items-center gap-2.5 rounded-lg border border-warning/40 bg-warning-soft px-4 py-2.5 text-sm">
      <Icon name="lock" size={16} class="shrink-0 text-warning" />
      <span class="text-fg-muted"><span class="font-medium text-fg">Driving in progress.</span> Model switching is disabled until parked.</span>
    </div>
  {/if}

  <Card title="Active model" icon="models">
    <svelte:fragment slot="actions">
      {#if canRollback}
        <Button variant="secondary" size="sm" icon="refresh-cw" loading={busy === "__rollback"} on:click={doRollback}>
          Roll back
        </Button>
      {/if}
    </svelte:fragment>
    {#if active}
      <div class="flex items-center gap-3">
        <div class="grid h-11 w-11 place-items-center rounded-xl border border-line bg-surface-2 text-accent">
          <Icon name="models" size={20} />
        </div>
        <div>
          <p class="font-semibold text-fg">{active.name}</p>
          <p class="text-xs text-fg-subtle">
            {[
              active.version ? `v${active.version}` : null,
              active.generation ? `gen ${active.generation}` : null,
              active.runner,
            ]
              .filter(Boolean)
              .join(" · ") || "Reported by the device"}
          </p>
        </div>
      </div>
    {:else if data?.running_default}
      <div class="flex items-center gap-3">
        <div class="grid h-11 w-11 place-items-center rounded-xl border border-line bg-surface-2 text-accent">
          <Icon name="models" size={20} />
        </div>
        <div>
          <p class="font-semibold text-fg">Default (stock) model</p>
          <p class="text-xs text-fg-subtle">The device is running its built-in model. Switch to one below to change it.</p>
        </div>
      </div>
    {:else}
      <p class="text-sm text-fg-muted">No active model reported yet. The device reports its running model on the next heartbeat.</p>
    {/if}
  </Card>

  <div class="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
    {#each data.models as m (m.id)}
      <div class="card p-4" class:opacity-60={!m.compatible}>
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <h4 class="truncate font-semibold text-fg">{m.name}</h4>
              {#if m.is_default}<span class="badge badge-neutral">Stock</span>{/if}
            </div>
            <p class="mt-1 line-clamp-2 text-xs text-fg-muted">{m.description}</p>
          </div>
          {#if m.active}
            <span class="badge badge-success shrink-0"><Icon name="check" size={12} /> Active</span>
          {/if}
        </div>
        <div class="mt-3 flex items-center justify-between border-t border-line pt-3 text-xs text-fg-subtle">
          <span>
            {[
              m.version ? `v${m.version}` : null,
              m.generation ? `gen ${m.generation}` : null,
              m.runner,
              m.size_bytes ? fmtBytes(m.size_bytes) : null,
            ]
              .filter(Boolean)
              .join(" · ") || "On-device model"}
          </span>
          {#if m.active}
            <span class="text-fg-subtle">Running</span>
          {:else if !m.compatible}
            <span class="badge badge-warning">Incompatible</span>
          {:else}
            <Button
              variant="secondary"
              size="sm"
              loading={busy === m.key}
              disabled={data.onroad || !!busy}
              on:click={() => doSwitch(m.key, m.name, m.is_default)}>
              Switch
            </Button>
          {/if}
        </div>
      </div>
    {/each}
  </div>
{/if}
