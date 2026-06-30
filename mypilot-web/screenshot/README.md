# Dashboard screenshot tooling

One-off tooling to (re)generate the README hero image (`docs/images/dashboard-live.png`): a styled,
dark-theme browser-frame mockup of the dashboard's **Live location** card with a device driving live
near xAI HQ in Palo Alto, with a road-following blue GPS trail.

This is **local/dev only** — not part of the product, not run in CI. Playwright is intentionally **not**
a committed dependency (it pulls a ~100 MB browser); install it ad-hoc when regenerating.

## Regenerate

Requires the local stack running (`make up`) and reachable on `localhost:18080`.

```bash
cd mypilot-web
npm install --no-save playwright && npx playwright install chromium   # ad-hoc, not committed

# 1) make the sim device appear live-driving in Palo Alto (prints a SESSION_TOKEN). Run in the api
#    container so it has the app + db + redis. It fetches a real road-following route from OSRM.
docker compose cp screenshot/setup_driving.py mypilot-api:/app/setup_driving.py
TOKEN=$(docker compose exec -T mypilot-api python setup_driving.py | grep SESSION_TOKEN | cut -d= -f2)

# 2) capture + composite into the framed mockup
SHOT_TOKEN="$TOKEN" SHOT_BASE="http://localhost:18080" SHOT_THEME=dark node screenshot/capture.mjs
cp /tmp/dashboard-hero-framed.png ../docs/images/dashboard-live.png
```

## Files
- `setup_driving.py` — seeds the simulated device as live-driving along a real OSRM road route ending
  at xAI HQ, clears other devices' presence, and mints a short-lived admin session. Run in the api
  container.
- `capture.mjs` — Playwright: logs in via the session cookie, loads the dashboard (dark), fits the map
  to the full trail (via the `_lmap` debug hook on the RouteMap container), screenshots the hero card,
  and composites it into the dark browser-frame mockup.

Adjust the route by editing `_WAYPOINTS` in `setup_driving.py` (lon,lat pairs; OSRM stitches the real
street geometry through them).
