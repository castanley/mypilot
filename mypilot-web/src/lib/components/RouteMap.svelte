<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { theme } from "$lib/stores/theme";

  // A polyline point: [lat, lon] (live trail) or [t, lat, lon] (route track). toLatLng handles both.
  type MapPoint = [number, number] | [number, number, number];

  // Theme-matched minimal basemaps (CARTO, free, no API key, OSM-based): Positron (light) and Dark
  // Matter (dark) are a deliberately sparse, label-light pair — the clean, low-clutter look that
  // makes the route line pop, rather than busy stock OSM tiles.
  const TILES = {
    light: {
      url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
      attribution: "&copy; OpenStreetMap &copy; CARTO",
      maxZoom: 20,
      subdomains: "abcd",
    },
    dark: {
      url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      attribution: "&copy; OpenStreetMap &copy; CARTO",
      maxZoom: 20,
      subdomains: "abcd",
    },
  } as const;

  // One or more polylines to draw. Each line is an ordered list of [lat,lon] or [t,lat,lon] points.
  export let lines: MapPoint[][] = [];
  // Optional start markers (e.g. the all-drives overview): [lat, lon, label?].
  export let markers: Array<{ lat: number; lon: number; label?: string; href?: string }> = [];
  export let height = "420px";
  // When false, the map is a STATIC thumbnail: no drag/zoom/scroll/controls (used by the route-tile
  // gallery, where each tile is click-through-to-drive, not pannable).
  export let interactive = true;
  // Optional live position marker (the compass arrow that rides the route during video playback).
  // {lat, lon, heading} — heading in degrees (0=N, 90=E); null hides it.
  export let marker: { lat: number; lon: number; heading: number } | null = null;
  // Follow mode (live driving): pan to the `marker` as it moves, keeping the current zoom, instead of
  // re-fitting bounds on every data change. Fits once initially, then tracks. Set an initial zoom for
  // the first frame so a single point isn't shown at world-zoom.
  export let follow = false;
  export let followZoom = 15;

  let el: HTMLDivElement;
  let map: any = null;
  let L: any = null;
  let layer: any = null;
  let posMarker: any = null; // the moving compass arrow (separate layer so it updates cheaply)
  let tileLayer: any = null; // current basemap, swapped on theme change
  let collapseTimer: number | null = null; // 5s timer to collapse the attribution to the ⓘ
  let followInit = false; // follow mode: whether we've set the initial view yet

  // Lines come in as [t, lat, lon] (or [lat, lon] for live trails); Leaflet wants [lat, lon].
  const toLatLng = (line: MapPoint[]): [number, number][] =>
    line.map((p) => (p.length >= 3 ? [p[1], p[2]] : [p[0], p[1]]) as [number, number]);

  // Leaflet touches window/document, so it must only load in the browser (SSR-safe dynamic import).
  onMount(async () => {
    L = (await import("leaflet")).default;
    await import("leaflet/dist/leaflet.css");
    map = L.map(el, {
      zoomControl: interactive,
      attributionControl: false, // we add a minimal one below (no Leaflet branding / flag)
      // Static thumbnail mode: kill every interaction so the tile is purely click-through.
      dragging: interactive,
      scrollWheelZoom: interactive,
      doubleClickZoom: interactive,
      boxZoom: interactive,
      keyboard: interactive,
      touchZoom: interactive,
      tap: interactive,
    });
    // Attribution is required by OSM/CARTO licensing AND must be visible by default (OSM's guidelines
    // forbid hiding it behind a hover/click). Shown on EVERY map — including the static gallery tiles,
    // which can't reveal-on-interaction — just styled small and low-contrast (see .mp-attrib). The
    // canonical wording is "© OpenStreetMap contributors © CARTO" with OSM linked to the copyright page.
    const ctrl = L.control.attribution({ prefix: false });
    ctrl.addAttribution(
      '<span class="mp-cred">© <a href="https://openstreetmap.org/copyright">OpenStreetMap</a> ' +
        'contributors © <a href="https://carto.com/attributions">CARTO</a></span>',
    );
    ctrl.addTo(map);
    const c = ctrl.getContainer();
    if (c) {
      c.classList.add("mp-attrib");
      // OSM-sanctioned: show the credit on load, then auto-collapse to a small ⓘ after 5s (the text
      // re-reveals on hover). Compliant because it IS visible by default first. On static gallery
      // tiles we leave it visible (they can't hover-reveal), so only collapse interactive maps.
      if (interactive) collapseTimer = window.setTimeout(() => c.classList.add("mp-collapsed"), 5000);
    }
    setTiles($theme);
    redraw();
    // Harmless debug hook: expose the Leaflet map on its container so external tooling (the README
    // screenshot capture under mypilot-web/screenshot) can fit the view to the full trail. The app
    // itself never reads this.
    (el as { _lmap?: unknown })._lmap = map;
  });

  onDestroy(() => {
    if (collapseTimer) clearTimeout(collapseTimer);
    if (map) {
      map.remove();
      map = null;
    }
  });

  // Redraw the route/markers when the data changes (after the map exists).
  $: if (map && L && (lines || markers)) redraw();
  // Update just the moving position marker (cheap — doesn't touch the route layer or bounds).
  $: if (map && L) updateMarker(marker);
  // Swap the basemap when the app theme flips (dark <-> light), live.
  $: if (map && L) setTiles($theme);

  function setTiles(mode: "dark" | "light") {
    if (!map || !L) return;
    const cfg = TILES[mode] ?? TILES.dark;
    if (tileLayer) tileLayer.remove();
    tileLayer = L.tileLayer(cfg.url, {
      maxZoom: cfg.maxZoom,
      // attribution handled once by the minimal control in onMount (no per-layer dup / Leaflet flag)
      ...("subdomains" in cfg ? { subdomains: cfg.subdomains } : {}),
    }).addTo(map);
    tileLayer.bringToBack(); // keep the basemap under the route/markers
  }

  function redraw() {
    if (!map || !L) return;
    if (layer) layer.remove();
    layer = L.layerGroup().addTo(map);

    const allBounds: any[] = [];
    for (const rawLine of lines) {
      if (!rawLine || rawLine.length === 0) continue;
      const line = toLatLng(rawLine);
      const pl = L.polyline(line, { color: "#3898ff", weight: 4, opacity: 0.85 }).addTo(layer);
      allBounds.push(pl.getBounds());
      // start (green) + end (red) dots for a single-drive view — but NOT in follow mode, where the
      // line is a growing live trail (an "end" dot would fight the moving compass arrow).
      if (lines.length === 1 && !follow) {
        L.circleMarker(line[0], { radius: 6, color: "#22c55e", fillColor: "#22c55e", fillOpacity: 1 })
          .addTo(layer)
          .bindPopup("Start");
        L.circleMarker(line[line.length - 1], { radius: 6, color: "#ef4444", fillColor: "#ef4444", fillOpacity: 1 })
          .addTo(layer)
          .bindPopup("End");
      }
    }
    for (const m of markers) {
      const cm = L.circleMarker([m.lat, m.lon], {
        radius: 5,
        color: "#3898ff",
        fillColor: "#3898ff",
        fillOpacity: 0.9,
      }).addTo(layer);
      if (m.label) cm.bindPopup(m.href ? `<a href="${m.href}">${m.label}</a>` : m.label);
      allBounds.push(L.latLngBounds([[m.lat, m.lon], [m.lat, m.lon]]));
    }

    // Follow mode: don't re-fit on every data change (that snaps/zooms as the trail grows). Set the
    // view ONCE on the first frame, then track the marker via updateMarker's panTo.
    if (follow) {
      if (!followInit && marker) {
        map.setView([marker.lat, marker.lon], followZoom);
        followInit = true;
      }
    } else if (allBounds.length) {
      let b = allBounds[0];
      for (const x of allBounds.slice(1)) b = b.extend(x);
      map.fitBounds(b, { padding: [30, 30], maxZoom: 16 });
    } else {
      map.setView([39.5, -98.35], 4); // continental US fallback when there's nothing to show
    }
    // The arrow lives on the map (not `layer`), so layer.remove() above didn't clear it — remove it
    // explicitly before re-adding, or each redraw (every heartbeat in follow mode, as the trail grows)
    // orphans the old arrow and they pile up.
    if (posMarker) { posMarker.remove(); posMarker = null; }
    updateMarker(marker);
  }

  // The blue compass arrow that rides the route during playback. A rotatable divIcon (SVG triangle
  // pointing "up" = travel direction, rotated by heading). Moving it just updates latlng + rotation
  // — no full redraw, so it stays smooth as the video plays.
  function arrowIcon(headingDeg: number) {
    return L.divIcon({
      className: "",
      iconSize: [26, 26],
      iconAnchor: [13, 13],
      html:
        `<div style="transform: rotate(${headingDeg}deg); width:26px; height:26px;">` +
        `<svg viewBox="0 0 24 24" width="26" height="26">` +
        `<circle cx="12" cy="12" r="11" fill="#3898ff" fill-opacity="0.25"/>` +
        `<path d="M12 3 L18 19 L12 15 L6 19 Z" fill="#3898ff" stroke="#fff" stroke-width="1.2" stroke-linejoin="round"/>` +
        `</svg></div>`,
    });
  }

  function updateMarker(m: { lat: number; lon: number; heading: number } | null) {
    if (!map || !L) return;
    if (!m) {
      if (posMarker) { posMarker.remove(); posMarker = null; }
      return;
    }
    if (!posMarker) {
      posMarker = L.marker([m.lat, m.lon], { icon: arrowIcon(m.heading), interactive: false, zIndexOffset: 1000 }).addTo(map);
    } else {
      posMarker.setLatLng([m.lat, m.lon]);
      posMarker.setIcon(arrowIcon(m.heading));
    }
    // Follow mode: keep the live position centered (smooth pan, current zoom preserved).
    if (follow && followInit) map.panTo([m.lat, m.lon], { animate: true, duration: 0.5 });
  }
</script>

<!-- `isolate` + `relative z-0` give the map its own stacking context, so Leaflet's internal pane/
     control z-indexes (200–800) stay scoped to the map and never paint over page chrome like the
     mobile nav drawer (z-40). -->
<div
  bind:this={el}
  style="height: {height}"
  class="mp-map relative z-0 w-full isolate overflow-hidden rounded-lg border border-border"></div>
