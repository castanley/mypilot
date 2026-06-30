<script lang="ts">
  import { getSettings } from "$lib/api";
  import { subscribeRealtime } from "$lib/realtime";
  import type { RealtimeEvent, SettingsResponse } from "$lib/types";
  import { cx } from "$lib/utils";
  import { onMount } from "svelte";
  import Icon from "./Icon.svelte";
  import SettingRow from "./SettingRow.svelte";

  export let deviceId: string;
  export let data: SettingsResponse;

  let activePanel = data.panels[0]?.id ?? "";
  $: panel = data.panels.find((p) => p.id === activePanel) ?? data.panels[0];

  let reconciling = false;
  // Refetch the real settings so the UI reflects the device's actual applied values.
  async function reconcile() {
    if (reconciling) return;
    reconciling = true;
    try {
      data = await getSettings(deviceId);
    } catch {
      /* keep current view */
    } finally {
      reconciling = false;
    }
  }

  // The device confirms each change asynchronously (setting_result) — reconcile on it.
  onMount(() => {
    const unsub = subscribeRealtime((e: RealtimeEvent) => {
      if (
        e.device_id === deviceId &&
        e.type === "device_event" &&
        (e as { event?: string }).event === "setting_result"
      ) {
        reconcile();
      }
    });
    return () => unsub();
  });
</script>

{#if data.onroad}
  <div class="mb-4 flex items-start gap-3 rounded-lg border border-warning/40 bg-warning-soft px-4 py-3">
    <Icon name="car" size={18} class="mt-0.5 shrink-0 text-warning" />
    <div class="text-sm">
      <p class="font-medium text-fg">Device is on the road</p>
      <p class="text-fg-muted">
        Safety-critical settings are locked until the car is parked. Other settings can still be changed.
      </p>
    </div>
  </div>
{/if}

{#if !data.synced}
  <div class="mb-4 flex items-start gap-3 rounded-lg border border-line bg-surface-2 px-4 py-3">
    <Icon name="wifi-off" size={18} class="mt-0.5 shrink-0 text-fg-subtle" />
    <div class="text-sm">
      <p class="font-medium text-fg">Waiting for device</p>
      <p class="text-fg-muted">
        This device is offline. Changes will be queued and synced when it reconnects.
      </p>
    </div>
  </div>
{/if}

<div class="grid grid-cols-1 gap-5 lg:grid-cols-[200px_1fr]">
  <!-- panel selector -->
  <nav class="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible" aria-label="Settings panels">
    {#each data.panels as p}
      <button
        type="button"
        on:click={() => (activePanel = p.id)}
        aria-current={p.id === activePanel ? "page" : undefined}
        class={cx(
          "flex shrink-0 items-center justify-between gap-2 rounded-md px-3 py-2 text-sm font-medium transition lg:w-full",
          p.id === activePanel
            ? "bg-surface-2 text-fg ring-1 ring-line-strong"
            : "text-fg-muted hover:bg-surface-2 hover:text-fg",
        )}>
        {p.label}
        <Icon name="chevron-right" size={14} class="hidden text-fg-subtle lg:block" />
      </button>
    {/each}
  </nav>

  <!-- active panel -->
  <div class="min-w-0 space-y-6">
    {#if panel}
      {#each panel.sections as section}
        <div>
          {#if section.name}
            <p class="section-label mb-1">{section.name}</p>
          {/if}
          <div class="card divide-y divide-line px-4 sm:px-5">
            {#each section.settings as setting (setting.key)}
              <SettingRow
                {deviceId}
                {setting}
                onroad={data.onroad}
                on:changed={() => setTimeout(reconcile, 3500)} />
            {/each}
          </div>
        </div>
      {/each}
    {/if}
  </div>
</div>
