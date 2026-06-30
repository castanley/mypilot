<script lang="ts">
  import { base } from "$app/paths";
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import {
    ApiError,
    getAudit,
    getDevice,
    getSettings,
    rebootDevice,
    unpairDevice,
    updateAlias,
  } from "$lib/api";
  import Button from "$lib/components/Button.svelte";
  import Card from "$lib/components/Card.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import Modal from "$lib/components/Modal.svelte";
  import RouteMap from "$lib/components/RouteMap.svelte";
  import Skeleton from "$lib/components/Skeleton.svelte";
  import StatusBadge from "$lib/components/StatusBadge.svelte";
  import SettingsPanelView from "$lib/components/SettingsPanelView.svelte";
  import DeviceModels from "$lib/components/DeviceModels.svelte";
  import DeviceSoftware from "$lib/components/DeviceSoftware.svelte";
  import DeviceBackups from "$lib/components/DeviceBackups.svelte";
  import { confirmAction } from "$lib/stores/confirm";
  import { toast } from "$lib/stores/toast";
  import { seedDevices, devices as deviceMap } from "$lib/stores/devices";
  import type { AuditEventOut, DeviceDetail, SettingsResponse } from "$lib/types";
  import { fmtBytes, fmtHeading, fmtSpeed, fullDate, gearLabel, gpsLabel, humanizeAction, parseVersion, relTime, shortId, thermalKind } from "$lib/utils";
  import { tempUnit, toggleTempUnit, fmtTemp } from "$lib/stores/units";

  // SSR-loaded initial data (see +page.server.ts) so the page paints populated on first byte instead
  // of flashing a skeleton. The shared store keeps the LIVE fields current (onroad, subsystems,
  // live_track, heartbeat, replaying) — `device` below holds the static detail (alias, platform, tabs).
  export let data: { device: DeviceDetail | null; audit: AuditEventOut[] };
  if (data.device) seedDevices([data.device]);

  $: id = $page.params.id ?? "";
  // Live node from the store (onroad/subsystems/live_track/heartbeat/replaying), updated by the WS.
  $: live = $deviceMap[id] ?? null;

  let loading = false;
  let notFound = data.device === null;
  let device: DeviceDetail | null = data.device;
  let settings: SettingsResponse | null = null;
  let audit: AuditEventOut[] = data.audit;
  let tab: "overview" | "settings" | "models" | "software" | "backups" | "activity" = "overview";

  let settingsLoading = false;
  let settingsLoaded = false;

  let renameOpen = false;
  let renameValue = "";
  let renameBusy = false;
  let actionBusy = false;

  async function load() {
    loading = true;
    notFound = false;
    try {
      const [d, a] = await Promise.all([getDevice(id), getAudit(id)]);
      device = d;
      audit = a;
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) notFound = true;
      else toast.error("Failed to load device");
    } finally {
      loading = false;
    }
  }

  async function loadSettings() {
    if (settingsLoaded || !device) return;
    settingsLoading = true;
    try {
      settings = await getSettings(id);
      settingsLoaded = true;
    } catch {
      toast.error("Failed to load settings");
    } finally {
      settingsLoading = false;
    }
  }

  $: if (tab === "settings") loadSettings();

  function openRename() {
    renameValue = device?.alias ?? "";
    renameOpen = true;
  }
  async function saveRename() {
    if (!renameValue.trim() || !device) return;
    renameBusy = true;
    try {
      device = await updateAlias(id, renameValue.trim());
      toast.success("Device renamed");
      renameOpen = false;
    } catch {
      toast.error("Rename failed");
    } finally {
      renameBusy = false;
    }
  }

  async function doReboot() {
    if (!device) return;
    const ok = await confirmAction({
      title: "Reboot device",
      message: `This will restart ${device.alias}. The device will be unavailable for about a minute.`,
      confirmLabel: "Reboot",
      danger: true,
    });
    if (!ok) return;
    actionBusy = true;
    try {
      await rebootDevice(id);
      toast.success("Reboot command sent");
      await load();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Reboot failed";
      toast.error("Could not reboot", msg);
    } finally {
      actionBusy = false;
    }
  }

  async function doUnpair() {
    if (!device) return;
    const ok = await confirmAction({
      title: "Unpair device",
      message: `This removes ${device.alias} from your control plane. Its trip and log history is kept; re-pair with a new code to reconnect it.`,
      confirmLabel: "Unpair device",
      danger: true,
      typeToConfirm: "UNPAIR",
    });
    if (!ok) return;
    actionBusy = true;
    try {
      await unpairDevice(id);
      toast.success("Device unpaired");
      // invalidateAll so the /devices list SSR load re-runs and drops the now-revoked device
      // (a bare goto reuses cached data and would still show it). ?all so we land on the LIST — if
      // exactly one device remains, a bare /devices would redirect into THAT device, which is jarring
      // right after an unpair (you expect to see your remaining fleet, not get dropped into a device).
      await goto(base + "/devices?all", { invalidateAll: true });
    } catch {
      toast.error("Unpair failed");
      actionBusy = false;
    }
  }

  // Re-seed from SSR data when the route param changes (the component is reused across /devices/[id],
  // so `data` updates without a remount). Key off the param id, NOT data.device — navigating to a bad
  // id returns data.device === null, and we must still flip to the not-found state and drop the old
  // device (guarding on `data.device` truthy would leave the previous device on screen). Reset ALL
  // per-device state: skeleton/loading (a reboot refresh on the old device must not bleed into the new
  // one), the active tab (lazy tab children load once on mount and don't refetch on a prop change), and
  // the settings cache + its in-flight flag.
  // Initialised from the page store (not the reactive `id`, which is in its temporal-dead-zone here)
  // so it matches `id`'s first value exactly and the block below doesn't fire a redundant reseed on mount.
  let loadedId: string | null = $page.params.id ?? "";
  $: if (id !== loadedId) {
    device = data.device;
    audit = data.audit;
    notFound = data.device === null;
    loading = false;
    tab = "overview";
    settings = null;
    settingsLoaded = false;
    settingsLoading = false;
    loadedId = id;
    if (data.device) seedDevices([data.device]); // refresh the store node for the new id
  }

  // No realtime handler here: the shared store owns the WS and keeps `live` (the store node) current.

  const tabs = [
    { id: "overview", label: "Overview", icon: "activity" },
    { id: "settings", label: "Settings", icon: "settings" },
    { id: "models", label: "Models", icon: "models" },
    { id: "software", label: "Software", icon: "software" },
    { id: "backups", label: "Backups", icon: "backups" },
    { id: "activity", label: "Activity", icon: "logs" },
  ] as const;

  // Detail rows: split the long version string into readable Core (upstream) + MyPilot (build date)
  // lines so it doesn't get truncated. ver.mypilot is null for non-MyPilot/unknown version formats.
  $: detailRows = device
    ? (() => {
        const ver = parseVersion(device.software_version);
        return [
          ["Platform", device.platform],
          ["Core", ver.core],
          ...(ver.mypilot ? [["Version", ver.mypilot]] : []),
          ["Branch", device.branch],
          ["Hardware ID", device.hardware_id],
          ["Activated", fullDate(device.activated_at)],
          ["Paired", fullDate(device.created_at)],
        ] as [string, string | null][];
      })()
    : [];
</script>

<svelte:head><title>{device?.alias ?? "Device"} · MyPilot</title></svelte:head>

<!-- ?all forces the device LIST (the loader redirects a bare /devices back here when this is the only
     device) so you can always reach the list — e.g. to pair a second device. -->
<a href={base + "/devices?all"} class="mb-4 inline-flex items-center gap-1.5 text-sm text-fg-muted hover:text-fg">
  <Icon name="arrow-left" size={16} /> Devices
</a>

{#if loading}
  <Skeleton height="2rem" width="16rem" />
  <div class="mt-6"><Skeleton height="20rem" /></div>
{:else if notFound}
  <div class="card">
    <EmptyState icon="alert-triangle" title="Device not found" description="This device may have been unpaired.">
      <!-- ?all so a missing/unpaired id lands on the LIST, not redirected into some other lone device. -->
      <Button variant="primary" href={base + "/devices?all"}>Back to devices</Button>
    </EmptyState>
  </div>
{:else if device}
  <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
    <div class="flex items-start gap-4">
      <div class="grid h-14 w-14 shrink-0 place-items-center rounded-2xl border border-line bg-surface-2 text-fg-muted">
        <Icon name="car" size={26} />
      </div>
      <div class="min-w-0">
        <div class="flex items-center gap-2">
          <!-- Only the title + rename share this row, so the name has the full width to truncate
               against; SIM/Replaying badges move to the status row below (they were eating width
               here and cutting the name short). -->
          <h1 class="truncate text-xl font-semibold tracking-tight text-fg sm:text-2xl">{device.alias}</h1>
          <button type="button" class="btn btn-ghost btn-icon-sm shrink-0" aria-label="Rename" on:click={openRename}>
            <Icon name="pencil" size={15} />
          </button>
        </div>
        <p class="mono mt-0.5 text-xs text-fg-subtle">{device.id}</p>
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <StatusBadge online={live?.online ?? device.online} onroad={live?.onroad ?? device.onroad} />
          {#if gearLabel(live?.gear)}<span class="badge {live?.gear === 'park' ? 'badge-neutral' : 'badge-accent'} shrink-0">{gearLabel(live?.gear)}</span>{/if}
          {#if device.is_simulated}<span class="badge badge-warning shrink-0">SIM</span>{/if}
          {#if live?.replaying}<span class="badge badge-accent shrink-0">Replaying</span>{/if}
        </div>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-2">
      <Button variant="secondary" icon="power" loading={actionBusy} disabled={live?.onroad ?? device.onroad} on:click={doReboot}>
        Reboot
      </Button>
      <Button variant="danger-soft" icon="trash" disabled={actionBusy} on:click={doUnpair}>Unpair</Button>
    </div>
  </div>

  {#if live?.onroad ?? device.onroad}
    <div class="mt-4 flex items-center gap-2.5 rounded-lg border border-warning/40 bg-warning-soft px-4 py-2.5 text-sm">
      <Icon name="lock" size={16} class="shrink-0 text-warning" />
      <span class="text-fg-muted">
        <span class="font-medium text-fg">Driving in progress.</span>
        Reboot and safety-critical settings are disabled until parked.
      </span>
    </div>
  {/if}

  <!-- tabs -->
  <div class="tab-scroll mt-6 flex gap-1 overflow-x-auto overflow-y-hidden border-b border-line">
    {#each tabs as t}
      <button
        type="button"
        on:click={() => (tab = t.id)}
        class="tab shrink-0 {tab === t.id ? 'tab-active' : ''}">
        <Icon name={t.icon} size={16} />
        {t.label}
        {#if tab === t.id}
          <span class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-accent"></span>
        {/if}
      </button>
    {/each}
  </div>

  <div class="mt-6">
    {#if tab === "overview"}
      <!-- Live fields come from the shared store node (`live`): subsystems, the live trail, onroad —
           kept current by the one WS subscription. `sub` mirrors the old status_detail.subsystems. -->
      {@const sub = live?.subsystems ?? null}
      {@const therm = sub?.thermal ?? null}
      {@const stor = sub?.storage ?? null}
      {@const drive = sub?.driving ?? null}
      {@const onroad = live?.onroad ?? device.onroad}
      {@const tk = thermalKind(therm?.status ?? null)}
      <div class="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div class="space-y-6 lg:col-span-2">
          <Card title="Telemetry" subtitle="Latest reported status" icon="activity">
            <div class="grid grid-cols-2 gap-4 sm:grid-cols-3">
              {#if onroad}
                <!-- Live speed leads the grid while driving (the at-a-glance "is it moving" signal);
                     hidden when parked since there's no live speed to show. -->
                <div class="rounded-lg border border-accent/30 bg-accent/10 p-3.5">
                  <div class="flex items-center gap-2 text-accent"><Icon name="car" size={15} /><span class="text-xs">Speed</span></div>
                  <p class="mt-1.5 text-sm font-semibold text-fg">{fmtSpeed(drive?.speed_ms)}</p>
                  {#if drive?.heading_deg != null}
                    <p class="mt-0.5 flex items-center gap-1 text-xs text-fg-subtle">
                      <!-- arrow-left points west (−90° from north); +90 makes it point north at
                           heading 0, then rotate by heading to the travel direction (Tailwind can't
                           do runtime rotation → inline style). -->
                      <span class="inline-flex" style="transform: rotate({drive.heading_deg + 90}deg)"><Icon name="arrow-left" size={12} /></span>
                      {fmtHeading(drive.heading_deg)}
                    </p>
                  {:else}
                    <p class="text-xs text-fg-subtle">Live · driving</p>
                  {/if}
                </div>
              {/if}
              <div class="rounded-lg border border-line bg-surface-2 p-3.5">
                <div class="flex items-center justify-between gap-2 text-fg-subtle">
                  <span class="flex items-center gap-2"><Icon name="thermometer" size={15} /><span class="text-xs">Thermal</span></span>
                  {#if therm?.max_c != null}
                    <button type="button" class="text-xs text-fg-subtle hover:text-fg" title="Toggle °C / °F" on:click={toggleTempUnit}>°{$tempUnit}</button>
                  {/if}
                </div>
                <p class="mt-1.5 text-sm font-semibold {tk === 'success' ? 'text-success' : tk === 'warning' ? 'text-warning' : tk === 'danger' ? 'text-danger' : 'text-fg'}">
                  {#if therm?.max_c != null}{fmtTemp(therm.max_c, $tempUnit)}{:else}<span class="capitalize">{therm?.status ?? "—"}</span>{/if}
                </p>
                {#if therm?.max_c != null && therm?.status}
                  <p class="text-xs capitalize text-fg-subtle">{therm.status}</p>
                {/if}
              </div>
              <div class="rounded-lg border border-line bg-surface-2 p-3.5">
                <div class="flex items-center gap-2 text-fg-subtle"><Icon name="hard-drive" size={15} /><span class="text-xs">Storage</span></div>
                <p class="mt-1.5 text-sm font-semibold text-fg">{stor?.used_pct != null ? stor.used_pct + "%" : "—"}</p>
                {#if stor?.used_bytes != null && stor?.total_bytes != null}
                  <p class="text-xs text-fg-subtle">{fmtBytes(stor.used_bytes)} / {fmtBytes(stor.total_bytes)}</p>
                {/if}
                {#if stor?.used_pct != null}
                  <div class="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
                    <div class="h-full rounded-full {stor.used_pct > 85 ? 'bg-danger' : stor.used_pct > 65 ? 'bg-warning' : 'bg-success'}" style="width: {stor.used_pct}%"></div>
                  </div>
                {/if}
              </div>
              <div class="rounded-lg border border-line bg-surface-2 p-3.5">
                <div class="flex items-center gap-2 text-fg-subtle"><Icon name="chip" size={15} /><span class="text-xs">Panda</span></div>
                <p class="mt-1.5 text-sm font-semibold capitalize text-fg">{sub?.panda?.status ?? "—"}</p>
              </div>
              <div class="rounded-lg border border-line bg-surface-2 p-3.5">
                <div class="flex items-center gap-2 text-fg-subtle"><Icon name="satellite" size={15} /><span class="text-xs">GPS</span></div>
                <p class="mt-1.5 text-sm font-semibold text-fg">{gpsLabel(sub?.gps?.status ?? null)}</p>
              </div>
              <div class="rounded-lg border border-line bg-surface-2 p-3.5">
                <div class="flex items-center gap-2 text-fg-subtle"><Icon name="clock" size={15} /><span class="text-xs">Heartbeat</span></div>
                <p class="mt-1.5 text-sm font-semibold text-fg">{relTime(live?.last_heartbeat_at ?? device.last_heartbeat_at)}</p>
              </div>
              <div class="rounded-lg border border-line bg-surface-2 p-3.5">
                <div class="flex items-center gap-2 text-fg-subtle"><Icon name="software" size={15} /><span class="text-xs">Status</span></div>
                <p class="mt-1.5 text-sm font-semibold capitalize text-fg">{device.status}</p>
              </div>
            </div>
          </Card>
          {#if onroad && drive?.latitude != null && drive?.longitude != null}
            <!-- Live location while driving: the accumulating trail (blue polyline) + a following map
                 that pans to the moving compass arrow. live_track is SSR-seeded so it survives a
                 refresh; the map follows the current position instead of re-fitting each heartbeat. -->
            <Card title="Live location" subtitle="Where the device is right now" icon="map" pad={false}>
              <RouteMap
                lines={live?.track?.length ? [live.track] : []}
                marker={{ lat: drive.latitude, lon: drive.longitude, heading: drive.heading_deg ?? 0 }}
                follow
                height="300px" />
            </Card>
          {/if}
        </div>
        <div class="space-y-6">
          <Card title="Details" icon="info">
            <dl class="space-y-3 text-sm">
              {#each detailRows as [k, v]}
                <div class="flex items-center justify-between gap-3">
                  <dt class="text-fg-subtle">{k}</dt>
                  <dd class="mono truncate font-medium text-fg">{v ?? "—"}</dd>
                </div>
              {/each}
            </dl>
          </Card>
          <Button variant="secondary" icon="settings" class="w-full" on:click={() => (tab = "settings")}>
            Configure settings
          </Button>
          <div class="grid grid-cols-2 gap-2">
            <Button variant="secondary" icon="routes" href={base + "/routes?device=" + id}>Routes</Button>
            <Button variant="secondary" icon="logs" href={base + "/logs?device=" + id}>Logs</Button>
          </div>
        </div>
      </div>
    {:else if tab === "settings"}
      {#if settingsLoading}
        <Skeleton height="24rem" />
      {:else if settings}
        <SettingsPanelView deviceId={id} data={settings} />
      {/if}
    {:else if tab === "models"}
      <DeviceModels deviceId={id} />
    {:else if tab === "software"}
      <DeviceSoftware deviceId={id} />
    {:else if tab === "backups"}
      <DeviceBackups deviceId={id} />
    {:else if tab === "activity"}
      <Card title="Activity" subtitle="Audit trail for this device" icon="logs">
        {#if audit.length === 0}
          <EmptyState icon="logs" title="No activity yet" description="Events for this device will appear here." />
        {:else}
          <ol class="relative space-y-0">
            {#each audit as ev, i (ev.id)}
              <li class="relative flex gap-4 pb-5 last:pb-0">
                {#if i < audit.length - 1}
                  <span class="absolute left-[7px] top-4 h-full w-px bg-line"></span>
                {/if}
                <span class="relative z-10 mt-1 grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full border-2 border-accent bg-bg"></span>
                <div class="min-w-0 flex-1">
                  <p class="text-sm font-medium text-fg">{humanizeAction(ev.action)}</p>
                  <p class="text-xs text-fg-subtle">
                    {ev.actor_type}{ev.actor_id ? " · " + shortId(ev.actor_id) : ""} · {fullDate(ev.created_at)}
                  </p>
                  {#if Object.keys(ev.event_metadata).length}
                    <pre class="mono mt-1.5 overflow-x-auto rounded-md border border-line bg-bg-subtle px-2.5 py-1.5 text-xs text-fg-muted">{JSON.stringify(ev.event_metadata)}</pre>
                  {/if}
                </div>
              </li>
            {/each}
          </ol>
        {/if}
      </Card>
    {/if}
  </div>
{/if}

<Modal open={renameOpen} title="Rename device" size="sm" on:close={() => (renameOpen = false)}>
  <label class="label" for="alias-input">Device name</label>
  <input id="alias-input" class="input" bind:value={renameValue} maxlength="60" placeholder="e.g. Daily — Model 3" />
  <p class="hint">A friendly name to identify this device across your fleet.</p>
  <svelte:fragment slot="footer">
    <Button variant="ghost" on:click={() => (renameOpen = false)}>Cancel</Button>
    <Button variant="primary" loading={renameBusy} disabled={!renameValue.trim()} on:click={saveRename}>Save</Button>
  </svelte:fragment>
</Modal>
