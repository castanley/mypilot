<script lang="ts">
  import { base } from "$app/paths";
  import { goto } from "$app/navigation";
  import { ApiError, deleteRoute, routeFileDownloadUrl } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import Card from "$lib/components/Card.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import { confirmAction } from "$lib/stores/confirm";
  import { toast } from "$lib/stores/toast";
  import type { RouteDetail } from "$lib/types";
  import { fmtBytes, fmtDistance, fmtDuration, fullDate } from "$lib/utils";

  export let data: { route: RouteDetail | null };
  $: route = data.route;

  let deleting = false;

  async function doDelete() {
    if (!route) return;
    const ok = await confirmAction({
      title: "Delete drive",
      message: `Permanently delete this drive and all ${route.files.length} segment file(s) from storage? This cannot be undone.`,
      confirmLabel: "Delete drive",
      danger: true,
    });
    if (!ok) return;
    deleting = true;
    try {
      const deviceId = route.device_id;
      await deleteRoute(route.id);
      toast.success("Drive deleted");
      goto(`${base}/routes?device=${deviceId}`);
    } catch (e) {
      toast.error("Delete failed", e instanceof ApiError ? e.message : undefined);
      deleting = false;
    }
  }
</script>

<svelte:head><title>{route?.alias ?? route?.name ?? "Drive"} · MyPilot</title></svelte:head>

<a href={base + "/routes"} class="mb-4 inline-flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg">
  <Icon name="arrow-left" size={16} /> Routes
</a>

{#if !route}
  <div class="card">
    <EmptyState icon="alert-triangle" title="Drive not found" description="This drive may have been deleted.">
      <Button variant="primary" href={base + "/routes"}>Back to routes</Button>
    </EmptyState>
  </div>
{:else}
  <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
    <div class="flex items-start gap-4">
      <div class="grid h-14 w-14 shrink-0 place-items-center rounded-2xl border border-line bg-surface-2 text-fg-muted">
        <Icon name="routes" size={26} />
      </div>
      <div class="min-w-0">
        <h1 class="truncate text-xl font-semibold tracking-tight text-fg sm:text-2xl">
          {route.alias ?? route.name}
        </h1>
        <p class="mono mt-0.5 text-xs text-fg-subtle">{route.name}</p>
        <div class="mt-2 flex items-center gap-2">
          <span
            class="badge capitalize {route.upload_status === 'complete'
              ? 'badge-success'
              : route.upload_status === 'failed'
                ? 'badge-danger'
                : 'badge-warning'}">{route.upload_status}</span>
          <a href={base + "/devices/" + route.device_id} class="badge badge-neutral hover:text-fg">
            <Icon name="car" size={12} /> Device
          </a>
        </div>
      </div>
    </div>
    <Button variant="danger-soft" icon="trash" loading={deleting} on:click={doDelete}>Delete drive</Button>
  </div>

  <div class="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
    <div class="lg:col-span-2">
      <Card title="Segment files" subtitle="Raw logs stored in your object storage" icon="logs">
        {#if route.files.length === 0}
          <p class="text-sm text-fg-muted">No files were uploaded for this drive.</p>
        {:else}
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-line text-left text-xs text-fg-subtle">
                  <th class="py-2 pr-3 font-medium">Segment</th>
                  <th class="py-2 pr-3 font-medium">File</th>
                  <th class="py-2 pr-3 font-medium">Kind</th>
                  <th class="py-2 pr-3 font-medium">Size</th>
                  <th class="py-2 pr-3"></th>
                </tr>
              </thead>
              <tbody>
                {#each route.files as f (f.id)}
                  <tr class="border-b border-line/60 last:border-0">
                    <td class="py-2.5 pr-3 text-fg-muted">{f.segment_index}</td>
                    <td class="py-2.5 pr-3 mono text-fg">{f.name}</td>
                    <td class="py-2.5 pr-3"><span class="badge badge-neutral uppercase">{f.kind}</span></td>
                    <td class="py-2.5 pr-3 text-fg-muted">{fmtBytes(f.size_bytes)}</td>
                    <td class="py-2.5 pr-3 text-right">
                      {#if f.uploaded}
                        <a
                          class="btn btn-secondary btn-sm"
                          href={routeFileDownloadUrl(route.id, f.id)}
                          download={f.name}>
                          <Icon name="download" size={15} /> Download
                        </a>
                      {:else}
                        <span class="badge badge-warning">Uploading</span>
                      {/if}
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </Card>
    </div>

    <div>
      <Card title="Details" icon="info">
        <dl class="space-y-3 text-sm">
          {#each [["Recorded", fullDate(route.started_at)], ["Ended", fullDate(route.ended_at)], ["Duration", fmtDuration(route.duration_s)], ["Distance", fmtDistance(route.distance_m)], ["From", route.start_location ?? "—"], ["To", route.end_location ?? "—"], ["Segments", String(route.segment_count)], ["Total size", fmtBytes(route.size_bytes)], ["Privacy", route.privacy_state]] as [k, v]}
            <div class="flex items-center justify-between gap-3">
              <dt class="text-fg-subtle">{k}</dt>
              <dd class="truncate font-medium text-fg capitalize">{v}</dd>
            </div>
          {/each}
        </dl>
      </Card>
    </div>
  </div>
{/if}
