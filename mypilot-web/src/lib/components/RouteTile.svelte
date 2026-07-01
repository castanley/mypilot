<script lang="ts">
  import { base } from "$app/paths";
  import RouteMap from "$lib/components/RouteMap.svelte";
  import type { RouteSummary, TrackPoint } from "$lib/types";
  import { getRouteTrack } from "$lib/api";
  import { clockTime, dayLabel, fmtDistance } from "$lib/utils";
  import { onMount, onDestroy } from "svelte";

  export let route: RouteSummary;

  let el: HTMLAnchorElement;
  let track: TrackPoint[] = [];
  let loaded = false;
  let failed = false;
  let observer: IntersectionObserver | null = null;

  // Lazy-load: only fetch the track + mount the mini-map once the tile scrolls into view, so a
  // gallery of many drives doesn't spin up N maps + N track fetches up front.
  async function load() {
    if (loaded) return;
    loaded = true;
    try {
      track = (await getRouteTrack(route.id)).track;
    } catch {
      failed = true;
    }
  }

  onMount(() => {
    if (typeof IntersectionObserver === "undefined") {
      load();
      return;
    }
    observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          load();
          observer?.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    observer.observe(el);
  });
  onDestroy(() => observer?.disconnect());
</script>

<a
  bind:this={el}
  href={base + "/drives/" + route.id}
  class="group block overflow-hidden rounded-lg border border-border bg-surface transition hover:border-accent/60 hover:shadow-glow">
  <div class="relative h-40 w-full bg-surface-2">
    {#if track.length}
      <RouteMap lines={[track]} height="160px" interactive={false} />
    {:else}
      <div class="flex h-40 items-center justify-center text-xs text-fg-subtle">
        {failed ? "Map unavailable" : "…"}
      </div>
    {/if}
    <!-- click-catcher: the mini-map is static, but keep clicks going to the link, not the map -->
    <div class="absolute inset-0"></div>
  </div>
  <div class="px-3 py-2">
    <p class="text-sm font-medium text-fg">{dayLabel(route.started_at ?? route.created_at)}</p>
    {#if route.start_location || route.end_location}
      <p class="mt-0.5 truncate text-xs text-fg" title="{route.start_location ?? '—'} → {route.end_location ?? '—'}">
        {route.start_location ?? "—"} → {route.end_location ?? "—"}
      </p>
    {/if}
    <p class="mt-0.5 text-xs text-fg-subtle">
      {clockTime(route.started_at ?? route.created_at)} · {fmtDistance(route.distance_m)}
    </p>
  </div>
</a>
