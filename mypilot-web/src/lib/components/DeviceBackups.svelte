<script lang="ts">
  import {
    ApiError,
    backupDownloadUrl,
    createBackup,
    deleteBackup,
    diffBackup,
    getBackups,
    restoreBackup,
  } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import Card from "$lib/components/Card.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import Skeleton from "$lib/components/Skeleton.svelte";
  import { confirmAction } from "$lib/stores/confirm";
  import { toast } from "$lib/stores/toast";
  import type { BackupDiffResponse, BackupOut } from "$lib/types";
  import { fmtBytes, fullDate } from "$lib/utils";
  import { onMount } from "svelte";

  export let deviceId: string;

  let backups: BackupOut[] = [];
  let loading = true;
  let creating = false;
  let busy = "";
  let diff: BackupDiffResponse | null = null;
  let diffOpen = false;
  let diffName = "";

  async function load() {
    try {
      backups = await getBackups(deviceId);
    } catch {
      toast.error("Failed to load backups");
    } finally {
      loading = false;
    }
  }

  async function doCreate() {
    creating = true;
    try {
      await createBackup(deviceId);
      toast.success("Backup created", "A snapshot of current settings was saved.");
      await load();
    } catch (e) {
      toast.error("Backup failed", e instanceof ApiError ? e.message : undefined);
    } finally {
      creating = false;
    }
  }

  async function showDiff(b: BackupOut) {
    busy = b.id + ":diff";
    try {
      diff = await diffBackup(deviceId, b.id);
      diffName = b.name;
      diffOpen = true;
    } catch (e) {
      toast.error("Diff failed", e instanceof ApiError ? e.message : undefined);
    } finally {
      busy = "";
    }
  }

  async function doRestore(b: BackupOut) {
    const ok = await confirmAction({
      title: "Restore settings",
      message: `Re-apply the settings from "${b.name}" to this device? Only applied while offroad; each change is audited.`,
      confirmLabel: "Restore",
      danger: true,
    });
    if (!ok) return;
    busy = b.id + ":restore";
    try {
      const res = await restoreBackup(deviceId, b.id, true);
      toast.success("Restore sent", res.detail);
    } catch (e) {
      toast.error("Restore failed", e instanceof ApiError ? e.message : undefined);
    } finally {
      busy = "";
    }
  }

  async function doDelete(b: BackupOut) {
    const ok = await confirmAction({
      title: "Delete backup",
      message: `Delete "${b.name}"? The snapshot is removed from storage.`,
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    busy = b.id + ":del";
    try {
      await deleteBackup(b.id);
      backups = backups.filter((x) => x.id !== b.id);
      toast.success("Backup deleted");
    } catch (e) {
      toast.error("Delete failed", e instanceof ApiError ? e.message : undefined);
    } finally {
      busy = "";
    }
  }

  onMount(load);
</script>

<div class="mb-4 flex items-center justify-between">
  <p class="text-sm text-fg-muted">Snapshot this device's settings, then restore or migrate them later.</p>
  <Button variant="primary" size="sm" icon="backups" loading={creating} on:click={doCreate}>
    Create backup
  </Button>
</div>

{#if loading}
  <Skeleton height="14rem" />
{:else if backups.length === 0}
  <div class="card">
    <EmptyState icon="backups" title="No backups yet" description="Create a settings snapshot you can restore or migrate to another device." />
  </div>
{:else}
  <div class="card divide-y divide-line">
    {#each backups as b (b.id)}
      <div class="flex flex-wrap items-center justify-between gap-3 p-4">
        <div class="min-w-0">
          <p class="font-medium text-fg">{b.name}</p>
          <p class="text-xs text-fg-subtle">
            {b.settings_count} settings · {fmtBytes(b.size_bytes)} · {fullDate(b.created_at)}
          </p>
        </div>
        <div class="flex items-center gap-2">
          <Button variant="ghost" size="sm" icon="activity" loading={busy === b.id + ":diff"} on:click={() => showDiff(b)}>Diff</Button>
          <a class="btn btn-secondary btn-sm" href={backupDownloadUrl(b.id)} download>
            <Icon name="download" size={15} /> JSON
          </a>
          <Button variant="secondary" size="sm" icon="refresh-cw" loading={busy === b.id + ":restore"} on:click={() => doRestore(b)}>Restore</Button>
          <button type="button" class="btn btn-ghost btn-icon-sm" aria-label="Delete" on:click={() => doDelete(b)}>
            <Icon name="trash" size={15} />
          </button>
        </div>
      </div>
    {/each}
  </div>
{/if}

<Modal open={diffOpen} title="Backup diff" size="md" on:close={() => (diffOpen = false)}>
  <p class="mb-3 text-sm text-fg-muted">
    Differences between <span class="font-medium text-fg">{diffName}</span> and the device's current settings.
  </p>
  {#if diff}
    {#if diff.changes.length === 0}
      <div class="rounded-lg border border-success/30 bg-success-soft px-4 py-3 text-sm text-fg-muted">
        No differences — the backup matches the device's current settings ({diff.unchanged} checked).
      </div>
    {:else}
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-line text-left text-xs text-fg-subtle">
              <th class="py-2 pr-3 font-medium">Setting</th>
              <th class="py-2 pr-3 font-medium">Current</th>
              <th class="py-2 pr-3 font-medium">Backup</th>
            </tr>
          </thead>
          <tbody>
            {#each diff.changes as c (c.key)}
              <tr class="border-b border-line/60 last:border-0">
                <td class="py-2 pr-3 text-fg">{c.label}</td>
                <td class="py-2 pr-3 mono text-fg-muted">{JSON.stringify(c.current_value)}</td>
                <td class="py-2 pr-3 mono text-accent">{JSON.stringify(c.backup_value)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <p class="mt-3 text-xs text-fg-subtle">{diff.unchanged} settings unchanged.</p>
    {/if}
  {/if}
</Modal>
