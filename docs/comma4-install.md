# Installing MyPilot on a comma 4 and pairing it

This is the real install + pairing flow for the comma 4 (codename **MICI**). There is **no
monolithic firmware image** — AGNOS is already on the device, and a fork is installed via the
device's **"Custom Software" URL**, which clones a GitHub branch and runs it.

- **Fork branch**: `mypilot-mici` on `github.com/castanley/openpilot` (clean SunnyPilot
  `release-mici` + the MyPilot agent — no driving/safety changes).
- **Install URL** (enter on the device): **`castanley/mypilot-mici`**
  (expands to `installer.comma.ai/castanley/mypilot-mici`).
- **Stack**: `https://mypilot.me` (the agent's default).

`release-mici` is a **prebuilt** branch, so install is fast (no on-device compile) and the
Python-only MyPilot additions run as-is.

## Before you start

- comma 4 currently running SunnyPilot `release-mici` (it is) and connected to Wi-Fi.
- A MyPilot Web account at `https://mypilot.me` (the owner account you set up).
- The device can reach `https://mypilot.me` (it's public, so Wi-Fi or LTE both work).

> Reinstalling replaces the running fork. Your **settings are backed up** by the device's normal
> mechanisms, but consider exporting a MyPilot backup first if you've already paired once.

## 1. Install the MyPilot branch

On the comma 4:

1. **Settings → Software → Uninstall** (or do a **factory reset** for a fully clean install).
2. The device reboots to the setup wizard. Connect Wi-Fi.
3. Choose **Custom Software (Advanced)**.
4. Enter the channel you want:
   - **release** (recommended): **`castanley/mypilot-mici`**
   - **staging** (release candidate): **`castanley/mypilot-mici-staging`**
   - **experimental bases** (generated but not yet validated on a physical comma 4):
     `castanley/mypilot-mici-op` (openpilot base), `castanley/mypilot-mici-frog` (frogpilot base)
5. Confirm. It downloads, installs (prebuilt = quick), and reboots into MyPilot.

Both branches stay current with upstream SunnyPilot automatically (the `sync-mypilot` GitHub
Action); the on-device updater pulls new commits on your branch.

## 2. Pair with MyPilot

On first boot the `mypilotd` agent generates a device key, requests a one-time pairing code, and
**shows it right on the device's home screen** (offroad) via an openpilot offroad alert — **no SSH
needed**.

1. On the comma 4 (offroad), read the **MyPilot pairing code** on the home screen. It refreshes
   automatically if it expires.
2. In a browser: `https://mypilot.me` → **Devices → Add device** → enter the code.
3. The comma 4 appears **online** with live telemetry, and the code clears from the screen.

The code is short-lived and one-time. If you don't see it on screen, the agent also logs it
(`[agent] pairing_code=…`) — see [Debugging](#debugging-on-device-ssh).

> **First time on a public Stack?** Rotate the admin password right away (account menu →
> **Change password**).

## 3. Verify

- Device shows **online**, with version/branch/car and storage/thermal once cereal is up.
- **Offroad**, change a setting in Web → Device → Settings; it applies on the device (via
  openpilot **Params**) and the value reconciles.
- Models / Software / Backups tabs show real device state.

## Configuration

The agent reads `/data/mypilot/config.json` (created on first run):

```json
{ "enabled": true, "stack_url": "https://mypilot.me", "drive_upload": "off" }
```

- Point at a different Stack: change `stack_url` (or set `MYPILOT_STACK_URL`).
- **Disable** MyPilot: set `"enabled": false` (the agent exits; the manager won't restart it into
  a running state). Re-enable by flipping it back.
- **Drive upload** (`drive_upload`, on-device only — never remotely configurable): `"off"` (default),
  `"qcamera"` (web-playable low-res road camera + per-segment metadata), or `"full"` (also the
  full-res road/wide/driver HEVC, download-only). Any non-`off` value makes MyPilot the upload target
  and disables comma's own `OnroadUploads`. See [privacy.md](privacy.md).

## What the agent does (this build)

| Action | Status |
|---|---|
| Pairing (on-screen), presence, telemetry | **Real** |
| Settings read/apply, reset, **restore backup** | **Real** (openpilot Params, offroad-gated) |
| Reboot | **Real** (offroad only) |
| Model switch / rollback | **Real**: sets `ModelManager_DownloadIndex`; SunnyPilot's Model Manager downloads + **SHA256-verifies** the bundle before activating. Revert-to-stock removes the active bundle. Offroad-only. |
| Software update / rollback | **Real**: sets `UpdaterTargetBranch` and nudges the updater; the device fetches the branch and applies it on the next reboot. Offroad-only. |
| Routes/logs upload | **Off by default** (privacy); opt-in. |

## Safety

- Everything driving-affecting is **offroad-only**, confirmed, and audited — in the agent **and**
  the Stack.
- The agent is a **non-critical sidecar**: it never touches `controlsd`, `pandad`, driver
  monitoring, torque, or panda safety. If it crashes, the manager restarts it and **driving is
  unaffected**. If `mypilot.me` is unreachable, the device drives normally.
- This build is based on **clean** `release-mici` and contains **no** driver-monitoring changes.

## Debugging on-device (SSH)

```bash
ssh comma@<device-ip>
tmux a -t mypilotd                 # live agent log (Ctrl-b d to detach)
cat /data/mypilot/config.json      # current config
cat /data/mypilot/identity.json    # device identity (keep private)
# the manager auto-restarts mypilotd; to force a restart, kill it:
pkill -f sunnypilot.mypilot.mypilotd
```

## Uninstall / revert

To go back to a clean (non-MyPilot) build, reinstall upstream via **Custom Software**:

- `install.sunnypilot.ai/release-mici` (upstream SunnyPilot), or
- `installer.comma.ai/commaai/release-mici` (upstream openpilot).
