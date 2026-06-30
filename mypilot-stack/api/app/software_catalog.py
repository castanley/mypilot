"""Software-release catalog (M7) — real, installable MyPilot channels for the comma 4 (MICI).

Each channel maps to a real branch on github.com/castanley/openpilot and a real comma installer
URL you enter in the device's "Custom Software" field (shorthand: ``castanley/<branch>``). The
device's *current* version/branch is reported by the device itself; these entries describe what
you can install/switch to. Branches are kept current with upstream SunnyPilot by the
``sync-mypilot`` GitHub Action.
"""

from __future__ import annotations

# version, channel, notes, is_current (latest on channel).
# Install URLs are NOT hard-coded — they're derived at request time from the fork config
# (Settings → Build / install source), so a fork just changes its GitHub owner/branches there.
RELEASES: list[dict] = [
    {
        "version": "2026.001.007",
        "channel": "release",
        "notes": "SunnyPilot release-mici + the MyPilot agent. Stable channel for daily use.",
        "is_current": True,
    },
    {
        "version": "2026.001.007-staging",
        "channel": "staging",
        "notes": "SunnyPilot release-mici-staging + the MyPilot agent. RC channel — test first.",
        "is_current": True,
    },
]
