# MyPilot Privacy

MyPilot is **local-first**. Nothing is sent to any third party. All data lives in your
self-hosted stack, and you decide what is captured and how long it is kept.

## What can be stored

**Nothing leaves the device by default except live status.** By default only device identity and
live status (storage/thermal/panda/GPS flags, onroad/offroad, version) reach the stack. Drive
recording is **off** until you turn it on.

Drive upload is a single on-device toggle (`drive_upload`, set on the device's MyPilot settings
screen — see [comma4-install.md](comma4-install.md)), with three modes:

| `drive_upload` mode | What uploads to your stack | Default |
| --- | --- | --- |
| **off** | Nothing. comma's own upload behavior is untouched. | ✅ default |
| **preview** (`qcamera`) | Low-res road-camera preview + per-segment metadata (qlog: time, distance, route id) | — |
| **full** | The above **plus** full-res road/wide/driver camera (download-only archive) | — |

Notes:
- The toggle is **on-device only** (privacy: it can't be flipped remotely from the web).
- Microphone/driver-camera bytes only ever leave the device in **full** mode, and only because they
  ride along with the full-res segment archive — there is no separate always-on mic/dcam upload.
- When `drive_upload` is anything but **off**, MyPilot also disables comma's own `OnroadUploads` so
  your drives go to *your* stack, not comma's.

## Your controls

- **Retention** — set how long routes and logs are kept, **per category** (`PUT /api/retention`
  with `route_days` / `log_days`; `0` = keep forever). Run it on demand (`POST /api/retention/run`).
- **Delete** — a single route (`DELETE /api/routes/{id}`) or **all of your routes**
  (`DELETE /api/routes`, optionally `?device_id=`). Delete individual logs.
- Delete/wipe a device from the control panel (revokes its key).
- Export settings and backups.
- Run fully local: leave `drive_upload` off and nothing but live status is stored.

## Principles

- Default behavior avoids uploading sensitive video.
- Route location data is never exposed without authentication.
- Raw logs are never exposed publicly.
- The device continues to function with uploads fully disabled.
