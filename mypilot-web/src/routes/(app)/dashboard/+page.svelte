<script lang="ts">
  import { base } from "$app/paths";
  import { page } from "$app/stores";
  import Button from "$lib/components/Button.svelte";
  import Card from "$lib/components/Card.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import PageHeader from "$lib/components/PageHeader.svelte";
  import Skeleton from "$lib/components/Skeleton.svelte";
  import StatCard from "$lib/components/StatCard.svelte";
  import StatusBadge from "$lib/components/StatusBadge.svelte";
  import RouteMap from "$lib/components/RouteMap.svelte";
  import { seedDevices, seedDriving, visibleDevices, drivers } from "$lib/stores/devices";
  import type { AuditEventOut, DeviceDetail, DeviceSummary, HealthResponse } from "$lib/types";
  import { fmtBytes, fmtHeading, fmtSpeed, gearLabel, humanizeAction, relTime, shortId } from "$lib/utils";

  // SSR-loaded initial data (see +page.server.ts) seeds the shared store synchronously (no flash);
  // the store keeps everything live (presence, onroad, speed/heading/trail) — no per-page WS handler.
  export let data: {
    devices: DeviceSummary[];
    health: HealthResponse | null;
    audit: AuditEventOut[];
    drivingSeed: Record<string, DeviceDetail>;
  };
  seedDevices(data.devices);
  seedDriving(data.drivingSeed); // devices already driving paint their hero instantly

  const loading = false;
  // health + audit are NOT realtime (/admin/health, admin audit) — keep them page-local. They are
  // ADMIN-ONLY surfaces: the loader only fetches them for the admin (others get health=null +
  // audit=[]), and the cards below render only when isAdmin — so a non-admin sees just their own
  // devices, never deployment-wide stats or the audit log.
  $: isAdmin = !!$page.data?.user?.is_admin;
  let health = data.health;
  let audit = data.audit;

  // `drivers` (store-derived): non-revoked devices that are onroad WITH a position — the hero. Now
  // also hides on a mid-drive disconnect (presence:false clears onroad+position in the store).
  $: online = $visibleDevices.filter((d) => d.online).length;
  $: onroad = $visibleDevices.filter((d) => d.onroad).length;
  // With exactly one device, the "devices" links go straight to it (single navigation, no hop through
  // /devices and its single-device redirect, which shows as a URL blip). Otherwise the list.
  $: devicesHref =
    $visibleDevices.length === 1 ? base + "/devices/" + $visibleDevices[0].id : base + "/devices";

  const healthComponents = [
    { key: "database", label: "Database", icon: "database" },
    { key: "redis", label: "Redis", icon: "redis" },
    { key: "object_storage", label: "Object storage", icon: "cloud" },
  ];

  // Render each backend's usage stats (shapes differ per component) into one subline.
  function usageLabel(key: string, u: Record<string, number> | null | undefined): string | null {
    if (!u) return null;
    const n = (x: number) => x.toLocaleString();
    if (key === "object_storage")
      return `${fmtBytes(u.used_bytes)} · ${n(u.object_count ?? 0)} object${u.object_count === 1 ? "" : "s"}`;
    if (key === "database") {
      const parts: string[] = [];
      if (u.size_bytes != null) parts.push(fmtBytes(u.size_bytes));
      parts.push(`${n(u.devices ?? 0)} device${u.devices === 1 ? "" : "s"}`);
      parts.push(`${n(u.routes ?? 0)} route${u.routes === 1 ? "" : "s"}`);
      return parts.join(" · ");
    }
    if (key === "redis") {
      const parts: string[] = [];
      if (u.used_bytes != null) parts.push(fmtBytes(u.used_bytes));
      parts.push(`${n(u.keys ?? 0)} key${u.keys === 1 ? "" : "s"}`);
      return parts.join(" · ");
    }
    return null;
  }
</script>

<svelte:head><title>Dashboard · MyPilot</title></svelte:head>

<PageHeader
  eyebrow="Overview"
  title="Fleet dashboard"
  description="Live status across every device paired to this control plane.">
  <svelte:fragment slot="actions">
    <Button variant="secondary" icon="add-device" href={base + "/devices/pair"}>Pair device</Button>
    <Button variant="primary" icon="devices" href={devicesHref}>View devices</Button>
  </svelte:fragment>
</PageHeader>

{#if $drivers.length}
  <!-- Live location hero: any device that's ON and sending coordinates (moving OR parked-but-running)
       leads the page above the stat cards, so the device list below stays compact. One wide card per
       device — live mini-map + big speed/heading (speed reads 0 while stopped). -->
  <section class="mb-6">
    <h2 class="mb-2 flex items-center gap-2 text-sm font-medium text-fg-muted">
      <Icon name="car" size={15} class="text-accent" /> Live location
    </h2>
    <div class="grid grid-cols-1 gap-4 {$drivers.length > 1 ? 'xl:grid-cols-2' : ''}">
      {#each $drivers as d (d.id)}
        <div class="card overflow-hidden">
          <!-- Map is full-width on top with the speed/heading panel underneath, so the live trail
               gets the whole card width to breathe. (Mobile already stacked this way; we keep that and
               extend it to every width rather than going side-by-side on sm+.) -->
          <div class="flex flex-col">
            <div class="h-44 sm:h-72">
              <!-- Live trail (blue polyline, like the routes page) + a following map that pans to the
                   moving arrow. The trail is SSR-seeded so it survives a page refresh. -->
              <RouteMap
                lines={d.track.length ? [d.track] : []}
                marker={{ lat: d.latitude ?? 0, lon: d.longitude ?? 0, heading: d.heading_deg ?? 0 }}
                follow
                height="100%" />
            </div>
            <div class="flex flex-col justify-center gap-1 p-5">
              <a href={base + "/devices/" + d.id} class="flex items-center gap-2 text-sm font-medium text-fg hover:text-accent">
                <span class="truncate">{d.alias}</span>
                {#if d.is_simulated}<span class="badge badge-warning shrink-0">SIM</span>{/if}
                {#if gearLabel(d.gear)}<span class="badge {d.gear === 'park' ? 'badge-neutral' : 'badge-accent'} shrink-0">{gearLabel(d.gear)}</span>{/if}
              </a>
              <p class="text-4xl font-semibold tracking-tight text-fg">{fmtSpeed(d.speed_ms)}</p>
              {#if d.heading_deg != null}
                <p class="flex items-center gap-1.5 text-sm text-fg-muted">
                  <span class="inline-flex" style="transform: rotate({d.heading_deg + 90}deg)"><Icon name="arrow-left" size={14} /></span>
                  Heading {fmtHeading(d.heading_deg)}
                </p>
              {:else if d.gear === "park"}
                <p class="text-sm text-fg-subtle">Parked</p>
              {/if}
            </div>
          </div>
        </div>
      {/each}
    </div>
  </section>
{/if}

<div class="grid grid-cols-2 gap-4 lg:grid-cols-4">
  {#if loading}
    {#each Array(4) as _}
      <div class="card panel-pad"><Skeleton height="3.5rem" /></div>
    {/each}
  {:else}
    <StatCard label="Devices" value={$visibleDevices.length} icon="devices" tone="accent" hint="Total paired" />
    <StatCard label="Online" value={online} icon="wifi" tone="success" hint={`${$visibleDevices.length - online} offline`} />
    <StatCard label="On road" value={onroad} icon="car" tone="warning" hint="Currently driving" />
    {#if isAdmin}
      <StatCard
        label="Control plane"
        value={health?.ok ? "Healthy" : "Degraded"}
        icon="shield-check"
        tone={health?.ok ? "success" : "danger"}
        hint={health?.ok ? "All systems go" : "Action needed"} />
    {/if}
  {/if}
</div>

<div class="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
  <div class={isAdmin ? "lg:col-span-2" : "lg:col-span-3"}>
    <Card title="Devices" subtitle="Real-time presence and driving state" icon="devices">
      <svelte:fragment slot="actions">
        <Button variant="ghost" size="sm" iconRight="chevron-right" href={devicesHref}>All</Button>
      </svelte:fragment>
      {#if loading}
        <div class="space-y-3">
          {#each Array(3) as _}<Skeleton height="3.5rem" />{/each}
        </div>
      {:else if $visibleDevices.length === 0}
        <p class="py-8 text-center text-sm text-fg-muted">No devices paired yet.</p>
      {:else}
        <ul class="-my-1 divide-y divide-line">
          {#each $visibleDevices as d (d.id)}
            <li>
              <a
                href={base + "/devices/" + d.id}
                class="group flex items-center gap-4 rounded-lg px-2 py-3 transition hover:bg-surface-2">
                <div class="grid h-10 w-10 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-fg-muted">
                  <Icon name="car" size={18} />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="flex items-center gap-2 truncate text-sm font-medium text-fg">
                    {d.alias}
                    {#if d.is_simulated}<span class="badge badge-warning shrink-0">SIM</span>{/if}
                  </p>
                  <p class="mono truncate text-xs text-fg-subtle">{shortId(d.id)} · {d.platform ?? "unknown"}</p>
                </div>
                <StatusBadge online={d.online} onroad={d.onroad} size="sm" />
                <Icon name="chevron-right" size={16} class="hidden shrink-0 text-fg-subtle group-hover:text-fg-muted sm:block" />
              </a>
            </li>
          {/each}
        </ul>
      {/if}
    </Card>
  </div>

  <!-- System health + the global audit trail are platform-admin surfaces — shown to the site admin
       only. A non-admin sees just the Devices card (which expands to full width above). -->
  {#if isAdmin}
    <div class="space-y-6">
      <Card title="System health" subtitle="Control-plane components" icon="activity">
        {#if loading}
          <div class="space-y-3">{#each Array(3) as _}<Skeleton height="2.5rem" />{/each}</div>
        {:else}
          <ul class="space-y-2.5">
            {#each healthComponents as c}
              {@const comp = health?.components[c.key]}
              <li class="flex items-center gap-3">
                <div class="grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-line bg-surface-2 text-fg-muted">
                  <Icon name={c.icon} size={15} />
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-sm font-medium text-fg">{c.label}</p>
                  {#if usageLabel(c.key, comp?.usage)}
                    <p class="truncate text-xs text-fg-subtle">{usageLabel(c.key, comp?.usage)}</p>
                  {:else if comp?.detail}
                    <p class="truncate text-xs text-fg-subtle">{comp.detail}</p>
                  {/if}
                </div>
                <span class={comp?.ok ? "badge badge-success" : "badge badge-danger"}>
                  <span class="dot {comp?.ok ? 'bg-success' : 'bg-danger'}"></span>
                  {comp?.ok ? "OK" : "Down"}
                </span>
              </li>
            {/each}
          </ul>
        {/if}
      </Card>

      <Card title="Recent activity" subtitle="Audit trail" icon="logs">
        {#if loading}
          <div class="space-y-3">{#each Array(4) as _}<Skeleton height="2rem" />{/each}</div>
        {:else}
          <ul class="space-y-3">
            {#each audit as ev (ev.id)}
              <li class="flex items-start gap-3">
                <span class="mt-1.5 dot shrink-0 bg-fg-subtle"></span>
                <div class="min-w-0 flex-1">
                  <p class="text-sm text-fg">{humanizeAction(ev.action)}</p>
                  <p class="text-xs text-fg-subtle">
                    {ev.actor_type} · {relTime(ev.created_at)}
                  </p>
                </div>
              </li>
            {/each}
          </ul>
        {/if}
      </Card>
    </div>
  {/if}
</div>
