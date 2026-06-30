<script lang="ts">
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import type { ModelOut } from "$lib/types";
  import { fmtBytes } from "$lib/utils";

  export let data: { models: ModelOut[] };
</script>

<svelte:head><title>Models · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="Fleet"
  title="Driving models"
  description="The model catalog available to your fleet. Switch and roll back per device from the device's Models tab — an offroad-only, audited action." />

{#if data.models.length === 0}
  <div class="card">
    <EmptyState icon="models" title="No models" description="The model catalog is empty." />
  </div>
{:else}
  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
    {#each data.models as m (m.id)}
      <div class="card p-5">
        <div class="flex items-start justify-between gap-3">
          <div class="grid h-11 w-11 place-items-center rounded-xl border border-line bg-surface-2 text-fg-muted">
            <Icon name="models" size={20} />
          </div>
          {#if m.is_default}
            <span class="badge badge-accent">Stock</span>
          {/if}
        </div>
        <h3 class="mt-4 text-base font-semibold text-fg">{m.name}</h3>
        <p class="mt-1 line-clamp-2 text-sm text-fg-muted">{m.description}</p>
        <div class="mt-4 grid grid-cols-2 gap-3 border-t border-line pt-3.5 text-xs">
          <div>
            <p class="text-fg-subtle">Version</p>
            <p class="mt-0.5 font-medium text-fg">{m.version}</p>
          </div>
          <div>
            <p class="text-fg-subtle">Generation</p>
            <p class="mt-0.5 font-medium text-fg">{m.generation ?? "—"}</p>
          </div>
          <div>
            <p class="text-fg-subtle">Runner</p>
            <p class="mt-0.5 font-medium text-fg">{m.runner ?? "—"}</p>
          </div>
          <div>
            <p class="text-fg-subtle">Size</p>
            <p class="mt-0.5 font-medium text-fg">{fmtBytes(m.size_bytes)}</p>
          </div>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-1.5">
          {#each m.compatible_device_types as dt}
            <span class="badge badge-neutral">{dt}</span>
          {/each}
        </div>
        <p class="mono mt-3 truncate text-[0.6875rem] text-fg-subtle" title={m.checksum}>
          sha256 {m.checksum.slice(0, 16)}…
        </p>
      </div>
    {/each}
  </div>
{/if}
