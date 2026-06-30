// Capture the dashboard "Live location" hero (live-driving Tesla in Palo Alto) and composite it into
// a styled dark browser-frame mockup for the README. Run on the host (chromium reachable + tile CDN
// reachable). LOCAL/dev tooling only — not shipped.
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.SHOT_BASE || "http://localhost:18080";
const TOKEN = process.env.SHOT_TOKEN;
const OUT = process.env.SHOT_OUT || "/tmp/dashboard-hero.png";
const OUT_FRAMED = process.env.SHOT_OUT_FRAMED || "/tmp/dashboard-hero-framed.png";
const THEME = process.env.SHOT_THEME || "dark";
if (!TOKEN) { console.error("SHOT_TOKEN required"); process.exit(1); }

const browser = await chromium.launch({ args: ["--no-sandbox"] });
const ctx = await browser.newContext({
  // Full dashboard width: hero (Live location) + the 4 stat cards + Devices/System health/Recent
  // activity all render at the lg: breakpoint (>=1024px). 1280 gives the full desktop layout.
  viewport: { width: 1280, height: 1100 },
  deviceScaleFactor: 2, // crisp 2x for a README
  colorScheme: "dark",
});
// Auth: set the session cookie + pin the theme to dark before the app boots.
const host = new URL(BASE).hostname;
await ctx.addCookies([{ name: "mypilot_session", value: TOKEN, domain: host, path: "/" }]);
await ctx.addInitScript((theme) => {
  try { localStorage.setItem("theme", theme); } catch {}
}, THEME);

const page = await ctx.newPage();
await page.goto(`${BASE}/dashboard`, { waitUntil: "networkidle", timeout: 45000 });

// Make sure dark theme is actually applied (the app reads localStorage on mount).
await page.evaluate((theme) => {
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.setAttribute("data-theme", theme);
}, THEME);

// Wait for the live-location hero + its map to exist and the Leaflet tiles to load.
const hero = page.locator("section:has-text('Live location'), :text('Live location')").first();
await hero.waitFor({ timeout: 20000 }).catch(() => {});
// Give Leaflet tiles + the blue polyline + arrow time to paint.
await page.waitForTimeout(4500);
// Best-effort: wait until at least some leaflet tiles are loaded.
await page.waitForFunction(() => {
  const t = document.querySelectorAll("img.leaflet-tile-loaded, .leaflet-tile-loaded");
  return t.length >= 4;
}, { timeout: 15000 }).catch(() => {});
await page.waitForTimeout(1500);

// The hero map follows the moving arrow (zoomed in), so only the last segment shows. For the
// screenshot we want the WHOLE curvy driven path visible — fit the Leaflet view to the polyline's
// bounds. Reach the Leaflet map + polyline via the DOM and fitBounds. (Static snapshot: no live
// telemetry is flowing, so the view won't re-center after we set it.)
await page.evaluate(() => {
  // RouteMap stashes its Leaflet map on the container as `_lmap` (debug hook). Fit the view to the
  // full driven path so the whole curvy trail shows, not just the followed marker.
  const container = document.querySelector(".leaflet-container");
  const map = container && container._lmap;
  if (!map || !map.eachLayer) return;
  let bounds = null;
  map.eachLayer((layer) => {
    const b = layer.getBounds && layer.getBounds();
    if (b && b.isValid && b.isValid()) bounds = bounds ? bounds.extend(b) : b;
  });
  if (bounds && bounds.isValid()) {
    map.fitBounds(bounds, { padding: [22, 22], animate: false });
  }
});
await page.waitForTimeout(2500); // let the newly-revealed tiles load
await page.waitForFunction(() => {
  const t = document.querySelectorAll("img.leaflet-tile-loaded, .leaflet-tile-loaded");
  return t.length >= 6;
}, { timeout: 12000 }).catch(() => {});
await page.waitForTimeout(1200);

// 1) Shot of the dashboard content (hero + stat cards + Devices/System health), CUT OFF before the
// "Recent activity" card. Capture <main> from its top down to where the Recent-activity card starts.
const main = page.locator("main").first();
const target = (await main.count()) ? main : page.locator("body");
await page.evaluate(() => window.scrollTo(0, 0));
await page.waitForTimeout(300);
const box = await target.boundingBox();
// Find the y of the "Recent activity" card so we can clip just above it.
const cutY = await page.evaluate(() => {
  const cards = Array.from(document.querySelectorAll("*"));
  const el = cards.find((n) => /Recent activity/i.test(n.textContent || "") &&
    n.children.length && /Recent activity/i.test(n.querySelector("h2,h3,p,span")?.textContent || n.textContent || ""));
  // Walk up to the enclosing card container.
  let card = document.evaluate("//*[contains(@class,'card')][.//text()[contains(.,'Recent activity')]]",
    document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
  return card ? Math.round(card.getBoundingClientRect().top + window.scrollY) : null;
});
if (box) {
  const height = cutY ? Math.max(200, cutY - box.y - 8) : box.height; // stop just above Recent activity
  await page.screenshot({
    path: OUT,
    clip: { x: Math.max(0, box.x), y: Math.max(0, box.y), width: box.width, height },
  });
} else {
  await page.screenshot({ path: OUT, fullPage: true });
}
console.log("dashboard ->", OUT, fs.existsSync(OUT) ? `(${fs.statSync(OUT).size} bytes)` : "(MISSING)");

// 2) Composite into a styled browser-frame mockup on a gradient backdrop. The window sizes to the
// captured dashboard (which is tall), with comfortable padding around it.
const shotB64 = fs.readFileSync(OUT).toString("base64");
const winW = 1200; // window content width; the shot scales to this
const framePage = await ctx.newPage();
await framePage.setViewportSize({ width: winW + 160, height: 900 });
await framePage.setContent(`
<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;padding:0}
  .stage{width:${winW + 160}px;display:inline-block;
    background:radial-gradient(1100px 640px at 30% 12%, #1e293b 0%, #0b1120 58%, #060912 100%);
    padding:64px 80px;box-sizing:border-box;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;}
  .win{width:${winW}px;border-radius:14px;overflow:hidden;background:#0f172a;
    box-shadow:0 50px 110px -25px rgba(0,0,0,.8), 0 0 0 1px rgba(148,163,184,.12);}
  .bar{height:46px;display:flex;align-items:center;gap:14px;padding:0 18px;
    background:linear-gradient(#1b2536,#161f30);border-bottom:1px solid rgba(148,163,184,.10);}
  .dot{width:12px;height:12px;border-radius:50%;}
  .r{background:#ff5f57}.y{background:#febc2e}.g{background:#28c840}
  .url{flex:1;text-align:center;color:#9fb0c7;font-size:13px;letter-spacing:.2px;
    background:#0b1322;border:1px solid rgba(148,163,184,.12);border-radius:8px;padding:6px 12px;max-width:520px;margin:0 auto;}
  .shot{display:block;width:100%}
</style></head><body>
  <div class="stage"><div class="win">
    <div class="bar"><span class="dot r"></span><span class="dot y"></span><span class="dot g"></span>
      <span class="url">mypilot.me/dashboard</span><span style="width:54px"></span></div>
    <img class="shot" src="data:image/png;base64,${shotB64}"/>
  </div></div>
</body></html>`, { waitUntil: "load" });
await framePage.waitForTimeout(500);
const stage = framePage.locator(".stage");
await stage.screenshot({ path: OUT_FRAMED });
console.log("framed ->", OUT_FRAMED, fs.existsSync(OUT_FRAMED) ? `(${fs.statSync(OUT_FRAMED).size} bytes)` : "(MISSING)");

await browser.close();
