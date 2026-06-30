<script lang="ts">
  import { base } from "$app/paths";
  import { getRouteTrack, routeFileDownloadUrl, routePlaylistUrl } from "$lib/api";
  import Card from "$lib/components/Card.svelte";
  import EmptyState from "$lib/components/EmptyState.svelte";
  import Icon from "$lib/components/Icon.svelte";
  import RouteMap from "$lib/components/RouteMap.svelte";
  import type { RouteDetail, TrackPoint } from "$lib/types";
  import { fmtBytes, fmtDistance, fmtDuration, fullDate } from "$lib/utils";
  import { onDestroy, onMount } from "svelte";

  export let data: { route: RouteDetail };
  $: route = data.route;

  // qcamera segments are web-playable (H.264/TS via HLS). fcamera/e/dcamera are raw HEVC — browsers
  // can't decode them inline, so they're offered as download-only archive files.
  $: hasVideo = route.files.some((f) => f.kind === "qcamera" && f.uploaded);
  $: archive = route.files.filter((f) => ["fcamera", "ecamera", "dcamera"].includes(f.kind) && f.uploaded);

  let video: HTMLVideoElement;
  let hls: import("hls.js").default | null = null;
  let playerError = "";

  async function setupPlayer() {
    if (!video || !hasVideo) return;
    const src = routePlaylistUrl(route.id);
    // Safari plays HLS natively; everywhere else use hls.js via MSE. Same-origin cookie auth is
    // used for the manifest + segment fetches (withCredentials).
    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = src;
      return;
    }
    try {
      const Hls = (await import("hls.js")).default;
      if (Hls.isSupported()) {
        hls = new Hls({ xhrSetup: (xhr) => { xhr.withCredentials = true; } });
        hls.on(Hls.Events.ERROR, (_e, d) => {
          if (d.fatal) playerError = "Playback error: " + d.details;
        });
        hls.loadSource(src);
        hls.attachMedia(video);
      } else {
        playerError = "This browser can't play HLS video.";
      }
    } catch (e) {
      playerError = "Failed to load the video player.";
    }
  }

  // Lazy-load the GPS track for the map (only when the drive has one). The full polyline is heavy,
  // so it's fetched on demand here rather than in the page's server load (see /routes/{id}/track).
  // Points are [t, lat, lon] with t = seconds since drive start, aligned with video playback time.
  let track: TrackPoint[] = [];
  let headings: number[] = []; // per-point travel direction (deg), precomputed from the track
  let trackError = false;
  async function loadTrack() {
    if (!route.has_track) return;
    try {
      track = (await getRouteTrack(route.id)).track;
      headings = computeHeadings(track);
    } catch {
      trackError = true;
    }
  }

  // Per-point heading. GPS points are often <1m apart (esp. when slow/stopped), so a bearing between
  // ADJACENT points is mostly noise. Instead, for each point look AHEAD until ~12m of travel has
  // accumulated and take the bearing to that point — a stable direction independent of point spacing.
  // Points with no qualifying look-ahead (end of route / long stop) inherit the previous heading, so
  // the arrow holds its last real direction instead of snapping to north.
  function computeHeadings(pts: TrackPoint[]): number[] {
    const MIN_M = 12;
    const out = new Array<number>(pts.length).fill(0);
    let last = 0;
    for (let i = 0; i < pts.length; i++) {
      let h: number | null = null;
      for (let j = i + 1; j < pts.length; j++) {
        if (haversineM(pts[i][1], pts[i][2], pts[j][1], pts[j][2]) >= MIN_M) {
          h = bearing(pts[i][1], pts[i][2], pts[j][1], pts[j][2]);
          break;
        }
      }
      last = h ?? last;
      out[i] = last;
    }
    // Backfill the leading run (before the first real movement) with the first known heading.
    const firstReal = out.find((v, i) => i === 0 || out[i] !== out[0]);
    if (firstReal !== undefined) for (let i = 0; i < out.length && out[i] === 0; i++) out[i] = firstReal;
    return out;
  }

  // The compass arrow position for the current video time. Binary-search the track by t, interpolate
  // between the two surrounding points for smooth motion, and derive heading from their bearing.
  let mapMarker: { lat: number; lon: number; heading: number } | null = null;

  function bearing(la1: number, lo1: number, la2: number, lo2: number): number {
    const r = Math.PI / 180;
    const y = Math.sin((lo2 - lo1) * r) * Math.cos(la2 * r);
    const x =
      Math.cos(la1 * r) * Math.sin(la2 * r) -
      Math.sin(la1 * r) * Math.cos(la2 * r) * Math.cos((lo2 - lo1) * r);
    return (Math.atan2(y, x) / r + 360) % 360;
  }

  function haversineM(la1: number, lo1: number, la2: number, lo2: number): number {
    const r = Math.PI / 180, R = 6371000;
    const dLa = (la2 - la1) * r, dLo = (lo2 - lo1) * r;
    const h =
      Math.sin(dLa / 2) ** 2 + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dLo / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  function onTimeUpdate() {
    if (!video || track.length === 0) return;
    const t = video.currentTime;
    // binary search for the last point with track[i][0] <= t
    let lo = 0, hi = track.length - 1, idx = 0;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (track[mid][0] <= t) { idx = mid; lo = mid + 1; } else { hi = mid - 1; }
    }
    const a = track[idx];
    const b = track[Math.min(idx + 1, track.length - 1)];
    // Interpolate between a and b by elapsed fraction — BUT only across a small time gap. A large gap
    // means the car was stationary (those fixes were dropped by the agent's speed filter), so sliding
    // across it would fake slow "creeping" between two far-apart jittered points. When the gap is big,
    // hold at a until the video actually reaches b (then it snaps to the real next position).
    const span = b[0] - a[0];
    const GAP_INTERP_MAX = 4; // s — only tween across normal ~1-2s point spacing, never a stop
    const f = span > 0 && span <= GAP_INTERP_MAX ? Math.min(1, Math.max(0, (t - a[0]) / span)) : 0;
    const lat = a[1] + (b[1] - a[1]) * f;
    const lon = a[2] + (b[2] - a[2]) * f;
    // Heading from the precomputed look-ahead array (stable; holds through stops).
    const heading = headings[idx] ?? 0;
    mapMarker = { lat, lon, heading };
  }

  onMount(() => { setupPlayer(); loadTrack(); });
  onDestroy(() => hls?.destroy());
</script>

<svelte:head><title>Drive · MyPilot</title></svelte:head>

<div class="mx-auto max-w-4xl">
  <a href={base + "/drives"} class="mb-4 inline-flex items-center gap-1.5 text-sm text-fg-muted transition hover:text-fg">
    <Icon name="arrow-left" size={15} /> Drives
  </a>

  <div class="mb-6">
    <h1 class="text-xl font-semibold tracking-tight text-fg sm:text-2xl">{fullDate(route.started_at ?? route.created_at)}</h1>
    <p class="mono mt-1 text-sm text-fg-subtle">{route.name}</p>
  </div>

  {#if hasVideo}
    <Card pad={false}>
      <!-- svelte-ignore a11y-media-has-caption -->
      <video
        bind:this={video}
        controls
        playsinline
        preload="metadata"
        on:timeupdate={onTimeUpdate}
        on:seeking={onTimeUpdate}
        class="aspect-video w-full rounded-t-xl bg-black"></video>
      {#if playerError}
        <p class="px-4 py-3 text-sm text-danger">{playerError}</p>
      {/if}
    </Card>
  {:else}
    <EmptyState
      icon="video"
      title="No playable video"
      description="This drive has no low-res (qcamera) video uploaded. Enable qcamera upload on the device to view it here." />
  {/if}

  {#if route.has_track}
    <div class="mt-6">
      <h2 class="mb-2 text-sm font-medium text-fg-muted">Route</h2>
      <Card pad={false}>
        {#if track.length}
          <RouteMap lines={[track]} marker={mapMarker} height="380px" />
        {:else}
          <div class="flex h-[380px] items-center justify-center text-sm text-fg-subtle">
            {trackError ? "Couldn't load the route map." : "Loading map…"}
          </div>
        {/if}
      </Card>
    </div>
  {/if}

  <div class="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
    {#each [["Duration", fmtDuration(route.duration_s)], ["Distance", fmtDistance(route.distance_m)], ["Segments", String(route.segment_count)], ["Size", fmtBytes(route.size_bytes)]] as [k, v]}
      <Card>
        <p class="text-xs text-fg-subtle">{k}</p>
        <p class="mt-1 text-lg font-semibold text-fg">{v}</p>
      </Card>
    {/each}
  </div>

  {#if archive.length}
    <Card title="Full-resolution archive" subtitle="Original HEVC — download to view in a desktop player" icon="video" class="mt-6">
      <ul class="divide-y divide-line">
        {#each archive as f (f.id)}
          <li class="flex items-center justify-between gap-3 py-2.5">
            <div class="min-w-0">
              <p class="mono truncate text-sm text-fg">seg {f.segment_index} · {f.name}</p>
              <p class="text-xs text-fg-subtle">{fmtBytes(f.size_bytes)}</p>
            </div>
            <a class="btn btn-secondary btn-sm" href={routeFileDownloadUrl(route.id, f.id)} download>
              <Icon name="arrow-left" size={14} class="rotate-[-90deg]" /> Download
            </a>
          </li>
        {/each}
      </ul>
    </Card>
  {/if}
</div>
