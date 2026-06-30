<script lang="ts">
  import { base } from "$app/paths";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import type { DeviceSummary, SoftwareReleaseOut } from "$lib/types";

  export let data: { releases: SoftwareReleaseOut[]; devices: DeviceSummary[] };

  $: channels = [...new Set(data.releases.map((r) => r.channel))];
</script>

<svelte:head><title>Software · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="System"
  title="Software"
  description="MyPilot release channels and your fleet's installed versions. Update or roll back a device from its Software tab — offroad only, and audited." />

{#if data.devices.length > 0}
  <div class="card mb-6 overflow-hidden">
    <div class="border-b border-line px-4 py-3 text-sm font-semibold text-fg">Fleet versions</div>
    <div class="divide-y divide-line">
      {#each data.devices as d (d.id)}
        <a href={base + "/devices/" + d.id} class="flex items-center justify-between gap-3 px-4 py-3 transition hover:bg-surface-2">
          <div class="flex items-center gap-3">
            <Icon name="car" size={18} class="text-fg-muted" />
            <span class="font-medium text-fg">{d.alias}</span>
          </div>
          <div class="flex items-center gap-3 text-sm">
            <span class="mono text-fg-muted">{d.software_version ?? "—"}</span>
            <span class="badge badge-neutral capitalize">{d.branch ?? "—"}</span>
            <Icon name="chevron-right" size={16} class="text-fg-subtle" />
          </div>
        </a>
      {/each}
    </div>
  </div>
{/if}

{#if data.releases.length === 0}
  <div class="card">
    <EmptyState icon="software" title="No releases" description="The release catalog is empty." />
  </div>
{:else}
  {#each channels as ch}
    <div class="mb-5">
      <p class="section-label mb-2 capitalize">{ch} channel</p>
      <div class="card divide-y divide-line">
        {#each data.releases.filter((r) => r.channel === ch) as r (r.id)}
          <div class="p-4">
            <div class="flex items-center gap-2">
              <p class="font-medium text-fg">{r.version}</p>
              {#if r.is_current}<span class="badge badge-accent">Latest</span>{/if}
            </div>
            <p class="mt-1 text-sm text-fg-muted">{r.notes}</p>
            {#if r.install_url}
              <p class="mono mt-1.5 text-xs text-fg-subtle">{r.install_url}</p>
            {/if}
          </div>
        {/each}
      </div>
    </div>
  {/each}
{/if}
