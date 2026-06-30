<script lang="ts">
  import { base } from "$app/paths";
  import { invalidateAll } from "$app/navigation";
  import {
    ApiError,
    backupDownloadUrl,
    deleteBackup,
    importBackup,
  } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import { confirmAction } from "$lib/stores/confirm";
  import { toast } from "$lib/stores/toast";
  import type { BackupOut, DeviceSummary } from "$lib/types";
  import { fmtBytes, fullDate } from "$lib/utils";

  export let data: { backups: BackupOut[]; devices: DeviceSummary[] };

  let fileInput: HTMLInputElement;
  let importing = false;

  function deviceAlias(id: string | null): string {
    if (!id) return "Imported";
    return data.devices.find((d) => d.id === id)?.alias ?? "Unknown device";
  }

  async function onFile(e: Event) {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (!file) return;
    importing = true;
    try {
      const text = await file.text();
      await importBackup(text);
      toast.success("Backup imported", "You can restore it to any device from its Backups tab.");
      await invalidateAll();
    } catch (err) {
      toast.error("Import failed", err instanceof ApiError ? err.message : "Invalid JSON");
    } finally {
      importing = false;
      if (fileInput) fileInput.value = "";
    }
  }

  async function doDelete(b: BackupOut) {
    const ok = await confirmAction({
      title: "Delete backup",
      message: `Delete "${b.name}"?`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteBackup(b.id);
      data.backups = data.backups.filter((x) => x.id !== b.id);
      toast.success("Backup deleted");
    } catch (e) {
      toast.error("Delete failed", e instanceof ApiError ? e.message : undefined);
    }
  }
</script>

<svelte:head><title>Backups · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="System"
  title="Backups"
  description="Settings snapshots you can download, restore, or migrate between devices. Create a backup from a device's Backups tab.">
  <svelte:fragment slot="actions">
    <input bind:this={fileInput} type="file" accept="application/json,.json" class="hidden" on:change={onFile} />
    <Button variant="secondary" icon="backups" loading={importing} on:click={() => fileInput?.click()}>
      Import JSON
    </Button>
  </svelte:fragment>
</PageHeader>

{#if data.backups.length === 0}
  <div class="card">
    <EmptyState icon="backups" title="No backups yet" description="Create a settings snapshot from a device's Backups tab, or import a backup JSON.">
      {#if data.devices.length > 0}
        <Button variant="primary" href={base + "/devices/" + data.devices[0].id}>Go to a device</Button>
      {/if}
    </EmptyState>
  </div>
{:else}
  <div class="card overflow-hidden">
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-line text-left text-xs text-fg-subtle">
            <th class="px-4 py-3 font-medium">Name</th>
            <th class="px-4 py-3 font-medium">Source</th>
            <th class="px-4 py-3 font-medium">Settings</th>
            <th class="px-4 py-3 font-medium">Size</th>
            <th class="px-4 py-3 font-medium">Created</th>
            <th class="px-4 py-3"></th>
          </tr>
        </thead>
        <tbody>
          {#each data.backups as b (b.id)}
            <tr class="border-b border-line/60 last:border-0 hover:bg-surface-2">
              <td class="px-4 py-3 font-medium text-fg">{b.name}</td>
              <td class="px-4 py-3 text-fg-muted">{b.source_alias ?? deviceAlias(b.device_id)}</td>
              <td class="px-4 py-3 text-fg-muted">{b.settings_count}</td>
              <td class="px-4 py-3 text-fg-muted">{fmtBytes(b.size_bytes)}</td>
              <td class="px-4 py-3 text-fg-muted">{fullDate(b.created_at)}</td>
              <td class="px-4 py-3">
                <div class="flex items-center justify-end gap-2">
                  <a class="btn btn-secondary btn-sm" href={backupDownloadUrl(b.id)} download>
                    <Icon name="download" size={15} /> JSON
                  </a>
                  <button type="button" class="btn btn-ghost btn-icon-sm" aria-label="Delete" on:click={() => doDelete(b)}>
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
