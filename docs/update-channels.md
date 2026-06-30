# Software update channels

How MyPilot models software **releases**, **channels**, **updates**, and **rollback** — all
self-hosted, offroad-only, and audited. Nothing here changes driving behavior.

## Channels (real)

A **channel** is a fork branch on `github.com/castanley/openpilot`, installed on a comma 4 via the
device's **Custom Software** field (comma's installer). The catalog ships two:

| Channel | Branch | Install URL (Custom Software) | Intent |
|---|---|---|---|
| `release` | `mypilot-mici` | `castanley/mypilot-mici` (→ `installer.comma.ai/castanley/mypilot-mici`) | Stable daily use |
| `staging` | `mypilot-mici-staging` | `castanley/mypilot-mici-staging` | Release candidate — test first |

Both branches = the corresponding **SunnyPilot release-mici / release-mici-staging** + the MyPilot
agent overlay, kept current by the `sync-mypilot` GitHub Action (§ Staying current). Channels are
seeded from `mypilot-stack/api/app/software_catalog.py`, exposed at `GET /api/software/releases`, and
shown on the **Software** hub (`/software`) + each device's **Software** tab.

> **Install bases.** The default channels use the **sunnypilot** base. The same recipe also
> publishes **openpilot** (`mypilot-mici-op`) and **frogpilot** (`mypilot-mici-frog`) bases as
> install-time choices — see [comma4-install.md](comma4-install.md) and the
> [build recipe](../mypilot-mici/README.md).

## Release metadata

Each release (`software_releases` table) carries:

- `version` — the SunnyPilot build (e.g. `2026.001.007`)
- `channel` — `release` or `staging`
- `notes` — shown in the UI
- `install_url` — the **real** comma installer URL for the branch
- `is_current` — the latest on its channel
- `build_time`, `created_at`

## Update flow (offroad-only, audited)

1. **User** picks a release in Device → Software (`POST /api/devices/:id/software/update`,
   `confirm: true`).
2. **Stack** verifies the device is **offroad** (rejects onroad), records the rollback target
   (`previous_software_version`), writes an audit event, and queues a `software_update` device
   command with `{version, channel, install_url}`.
3. **Device** applies it: the agent sets `UpdaterTargetBranch` and nudges
   `system/updated/updated.py`; the device fetches the branch and applies it on the next reboot,
   then reports the new version on the next heartbeat. The Stack reconciles the device's version on
   the command result.
4. **Rollback** (`POST …/software/rollback`) re-runs the same flow targeting the previously
   installed version.

```
Web ──update(version)──▶ Stack ──queue software_update──▶ Device
                          │                                  │ install (offroad), reboot
 device.software.update ◀─┘                                  │
                          ◀────── heartbeat: new version ────┘
```

Safety: updates are **offroad-only**, require **confirmation**, and are **audited**. The device
performs the install with its own updater — the Stack only sends intent.

## Install URLs (real)

`install_url` is the **comma installer URL** for the branch — `installer.comma.ai/<user>/<branch>`
(shorthand `<user>/<branch>` in the device's Custom Software field). comma's installer clones the
public fork at that branch and runs it; `release-mici` is **prebuilt**, so install is fast (no
on-device compile). No custom installer service is needed.

## Staying current with SunnyPilot

The delivery branches track upstream automatically via the **`sync-mypilot`** GitHub Action on
`castanley/openpilot` (daily + manual). Each run **clones this monorepo and runs
`mypilot-mici/publish.sh`**, rebuilding every `mypilot-*` branch as *latest upstream base + the
freshly assembled MyPilot overlay* and pushing only what changed. Canonical workflow:
[`deploy/fork/sync-mypilot.yml`](../deploy/fork/sync-mypilot.yml). Keep Actions enabled on the
delivery repo; trigger manually under Actions → sync-mypilot → Run workflow. See
[go-live.md](go-live.md).

## Fork branding & your Stack URL

Pointing a build at your Stack is **one file** — `mypilot-agent/mypilot_agent/fork.json`
(`{ "stack_url": "https://your-stack" }`), which the recipe vendors into every device branch.
On-device precedence is `MYPILOT_STACK_URL` env > `/data/mypilot/config.json` > `fork.json` >
built-in default. Set the panel's install source in **Settings**. Any on-device UI branding is
**labels only** — upstream safety systems (controlsd, pandad, driver monitoring, torque/panda
safety) are left **untouched**. See [forking.md](forking.md).
