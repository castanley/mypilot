#!/usr/bin/env python3
"""Idempotently turn a fresh upstream sunnypilot tree into the MyPilot device image.

Run from the fork repo root after ``assemble.py`` has overlaid ``sunnypilot/mypilot/`` (the agent)
and the base's UI files. This script encodes EVERY device-side edit that makes MyPilot MyPilot, so
the published image is the reproducible output of ``assemble.py build`` — never a hand patch that a
rebuild would silently drop. It:

  1. registers the MyPilot agent (mypilotd) as a non-critical, import-safe ``PythonProcess`` and
     fixes the registration so it always lands in ``managed_processes``;
  2. tears down sunnylink — removes the five cloud phone-home daemons and the now-orphaned helper
     shims/import — so the device never connects to ``athena.sunnylink.ai`` / ``stg.api.sunnypilot.ai``;
  3. force-disables the in-UI sunnylink worker, hides its sidebar status, and skips its onboarding
     consent screen (the ``SunnylinkEnabled`` param defaults "1" and can't be changed on a prebuilt
     ``params_pyx.so``, so we override at the read sites instead);
  4. rebrands the user-visible "sunnypilot" strings to "MyPilot" and points Terms at mypilot.me;
  5. swaps the mici sunnylink settings panel for the MyPilot Link panel (the UI files are vendored
     by assemble.py); and
  6. registers the on-screen pairing alert key.

DESIGN: every edit is idempotent (re-running is a no-op) and FAIL-LOUD — if an expected anchor is
missing (e.g. an upstream refactor moved it), we raise so the build fails instead of silently
shipping an image that re-enables phone-home or never launches the agent. We use a plain
``PythonProcess`` (not ``DaemonProcess``, which needs a PID param declared in the compiled
``params_keys.h`` — impossible on a prebuilt branch). No driving/safety code is touched.

Any per-build private layers are applied on top of this separately; they are intentionally NOT here
(this produces the clean, publishable image).
"""

from __future__ import annotations

import json
import os
import re
import sys

VERSION_H = "sunnypilot/common/version.h"
# Version becomes  <BASE_TAG>-<upstream-version>-mypilot-<base-date>-<NN>  e.g.
#   sunnypilot-2026.002.000-mypilot-2026.06.26-18
# BASE_TAG names the upstream base (sunnypilot / frogpilot / openpilot, spelled out for clarity); the
# "mypilot" marker makes it obvious this is a MyPilot build; the date is the BASE snapshot's commit
# date (not wall-clock) with a per-day build counter, so the version reflects real revisions.
BASE_TAG = "sunnypilot"

PROC_PATH = "system/manager/process_config.py"
UI_STATE_PATH = "selfdrive/ui/sunnypilot/ui_state.py"
SIDEBAR_PATH = "selfdrive/ui/sunnypilot/layouts/sidebar.py"
SETTINGS_PATH = "selfdrive/ui/sunnypilot/mici/layouts/settings.py"
ONBOARD_MICI_PATH = "selfdrive/ui/mici/layouts/onboarding.py"
ONBOARD_PATH = "selfdrive/ui/layouts/onboarding.py"
HOME_PATH = "selfdrive/ui/mici/layouts/home.py"
DEVICE_PATH = "selfdrive/ui/mici/layouts/settings/device.py"
TOGGLES_PATH = "selfdrive/ui/mici/layouts/settings/toggles.py"
FIREHOSE_PATH = "selfdrive/ui/mici/layouts/settings/firehose.py"
ALERT_RENDERER_PATH = "selfdrive/ui/mici/onroad/alert_renderer.py"
ROAD_VIEW_PATH = "selfdrive/ui/mici/onroad/augmented_road_view.py"
OFFROAD_ALERTS_PATH = "selfdrive/ui/mici/layouts/offroad_alerts.py"
SETUP_PATH = "system/ui/mici_setup.py"
SUNNYLINK_PANEL = "selfdrive/ui/sunnypilot/mici/layouts/sunnylink.py"
SUNNYLINK_DIALOG = "selfdrive/ui/sunnypilot/mici/widgets/sunnylink_pairing_dialog.py"

MODULE = "sunnypilot.mypilot.mypilotd"
ALERTS_PATH = "selfdrive/selfdrived/alerts_offroad.json"
ALERT_KEY = "Offroad_MyPilotPairing"
ALERT_ENTRY = {
    "text": "MyPilot pairing code: %1\nEnter it in MyPilot Web → Devices → Add device.",
    "severity": 1,
}


# --- patch primitives -------------------------------------------------------------------------

class AnchorError(RuntimeError):
    """An expected anchor was not found — fail the build rather than ship a broken/insecure image."""


def _read(path: str) -> str:
    with open(path) as fh:
        return fh.read()


def _write(path: str, src: str) -> None:
    with open(path, "w") as fh:
        fh.write(src)


def _replace_once(path: str, old: str, new: str, *, already: str, what: str) -> None:
    """Replace exactly one occurrence of ``old`` with ``new``. Idempotent via ``already`` sentinel;
    raises AnchorError if ``old`` is absent and the edit hasn't already been applied."""
    src = _read(path)
    if already in src:
        print(f"[mypilot] {what}: already applied")
        return
    count = src.count(old)
    if count != 1:
        raise AnchorError(f"{what}: expected exactly 1 occurrence of anchor in {path}, found {count}")
    _write(path, src.replace(old, new, 1))
    print(f"[mypilot] {what}: patched {path}")


def _remove_block(path: str, block: str, *, what: str, required: bool = True) -> None:
    """Remove a verbatim block. Idempotent (no-op if already gone). Raises if required & absent."""
    src = _read(path)
    if block not in src:
        if required:
            raise AnchorError(f"{what}: block not found in {path} (upstream changed?)")
        print(f"[mypilot] {what}: nothing to remove")
        return
    _write(path, src.replace(block, "", 1))
    print(f"[mypilot] {what}: removed block from {path}")


# --- 1 + 5: register the agent so it ALWAYS lands in managed_processes -------------------------

def _register_process() -> None:
    """Insert the mypilotd registration into the `procs` list ABOVE the
    `managed_processes = {p.name: p for p in procs}` line so it is always included. The previous
    fallback appended `procs += [...]` AFTER that line, so on an anchor-miss the agent was added to
    `procs` but never entered `managed_processes` and never launched — silently. We anchor on the
    stable `managed_processes = {` construction line, which every openpilot/sunnypilot tree ends with."""
    src = _read(PROC_PATH)
    if MODULE in src:
        print("[mypilot] mypilotd already registered")
        return
    block = (
        "procs += [\n"
        "  # MyPilot — self-hosted control plane agent. Non-critical sidecar; import-safe launcher,\n"
        "  # never in the driving path. restart_if_crash=True so a transient crash self-heals on the\n"
        "  # next manager cycle (ensure_running only restarts crashed procs when this is set).\n"
        f'  PythonProcess("mypilotd", "{MODULE}", always_run, restart_if_crash=True),\n'
        "]\n\n"
    )
    marker = "managed_processes = {p.name: p for p in procs}"
    if marker not in src:
        raise AnchorError(f"register_process: '{marker}' not found in {PROC_PATH}")
    if src.count(marker) != 1:
        raise AnchorError(f"register_process: '{marker}' found {src.count(marker)}x in {PROC_PATH}")
    src = src.replace(marker, block + marker, 1)
    _write(PROC_PATH, src)
    print("[mypilot] registered mypilotd above managed_processes in", PROC_PATH)


# --- 2: tear down sunnylink cloud daemons ------------------------------------------------------

def _disable_sunnylink_daemons() -> None:
    """Remove the five sunnylink phone-home registrations AND the now-orphaned shim defs + import,
    in one pass. Order matters: the shims/import are only safe to delete because their sole callers
    (the registrations) are removed in the same edit — otherwise process_config.py would reference
    undefined names and the manager would crash at import."""
    src = _read(PROC_PATH)
    # Self-validating idempotency: only treat as "already done" when NONE of the phone-home daemons
    # remain. If a future upstream refactor renamed just one, we must not silently skip the rest —
    # we fall through and the verbatim-block removal below raises AnchorError on the drift.
    daemon_needles = ("manage_sunnylinkd", "sunnylink_registration_manager", '"statsd_sp"',
                      "sunnylink.backups.manager", "sunnylink.uploader")
    if not any(n in src for n in daemon_needles):
        print("[mypilot] sunnylink daemons: already removed")
        return

    blocks = [
        # the "# sunnylink <3" daemon cluster
        ('\n  # sunnylink <3\n'
         '  DaemonProcess("manage_sunnylinkd", "sunnypilot.sunnylink.athena.manage_sunnylinkd", "SunnylinkdPid"),\n'
         '  PythonProcess("sunnylink_registration_manager", "sunnypilot.sunnylink.registration_manager", sunnylink_need_register_shim),\n'
         '  PythonProcess("statsd_sp", "sunnypilot.sunnylink.statsd", and_(always_run, sunnylink_ready_shim)),\n',
         '\n'),
        # backup manager (with its "# Backup" comment)
        ('\n  # Backup\n'
         '  PythonProcess("backup_manager", "sunnypilot.sunnylink.backups.manager", and_(only_offroad, sunnylink_ready_shim)),\n',
         '\n'),
        # conditional uploader block
        ('\nif os.path.exists("../../sunnypilot/sunnylink/uploader.py"):\n'
         '  procs += [PythonProcess("sunnylink_uploader", "sunnypilot.sunnylink.uploader", use_sunnylink_uploader_shim)]\n',
         '\n'),
        # the three orphaned shim defs
        ('\ndef sunnylink_ready_shim(started, params, CP: car.CarParams) -> bool:\n'
         '  """Shim for sunnylink_ready to match the process manager signature."""\n'
         '  return sunnylink_ready(params)\n'
         '\ndef sunnylink_need_register_shim(started, params, CP: car.CarParams) -> bool:\n'
         '  """Shim for sunnylink_need_register to match the process manager signature."""\n'
         '  return sunnylink_need_register(params)\n'
         '\ndef use_sunnylink_uploader_shim(started, params, CP: car.CarParams) -> bool:\n'
         '  """Shim for use_sunnylink_uploader to match the process manager signature."""\n'
         '  return use_sunnylink_uploader(params)\n',
         ''),
        # the now-unused import
        ('from openpilot.sunnypilot.sunnylink.utils import sunnylink_need_register, sunnylink_ready, use_sunnylink_uploader\n',
         ''),
    ]
    for old, new in blocks:
        if old not in src:
            raise AnchorError(f"disable_sunnylink: a sunnylink block was not found verbatim in {PROC_PATH} (upstream changed?)")
        src = src.replace(old, new, 1)

    # Belt-and-suspenders: no live sunnylink daemon registration may survive.
    for needle in ("manage_sunnylinkd", "sunnylink_registration_manager",
                   '"statsd_sp"', "sunnylink.backups.manager", "sunnylink.uploader"):
        if needle in src:
            raise AnchorError(f"disable_sunnylink: '{needle}' still present after teardown in {PROC_PATH}")
    _write(PROC_PATH, src)
    print("[mypilot] sunnylink cloud daemons + orphaned shims removed from", PROC_PATH)


# --- 3: force-disable the in-UI sunnylink worker + sidebar + consent ---------------------------

def _disable_sunnylink_ui() -> None:
    _replace_once(
        UI_STATE_PATH,
        '    self.sunnylink_enabled = self.params.get_bool("SunnylinkEnabled")',
        ('    # MyPilot: sunnylink is replaced by the MyPilot control plane. Force-disable the in-UI\n'
         '    # SunnylinkState worker (it fetches roles/users from stg.api.sunnypilot.ai) and the\n'
         '    # sidebar status, regardless of SunnylinkEnabled (defaults "1" in precompiled params).\n'
         '    self.sunnylink_enabled = False'),
        already="self.sunnylink_enabled = False",
        what="ui_state sunnylink disable",
    )
    _replace_once(
        SIDEBAR_PATH,
        "    metrics = [_temp, _panda, _connect, self._sunnylink_status]",
        ("    # MyPilot: drop the persistent SUNNYLINK status tile (sunnylink is replaced by MyPilot).\n"
         "    metrics = [_temp, _panda, _connect]"),
        already="metrics = [_temp, _panda, _connect]",
        what="sidebar sunnylink metric drop",
    )
    _replace_once(
        ONBOARD_MICI_PATH,
        ('    self._sunnylink_consent_done: bool = ui_state.params.get("CompletedSunnylinkConsentVersion") in {\n'
         "      sunnylink_consent_version, sunnylink_consent_declined\n"
         "    }"),
        ("    # MyPilot: never show the sunnylink consent/pairing screen (sunnylink is replaced by the\n"
         "    # MyPilot control plane; pairing happens via Settings -> MyPilot Link instead).\n"
         "    self._sunnylink_consent_done: bool = True"),
        already="self._sunnylink_consent_done: bool = True",
        what="onboarding sunnylink consent skip",
    )


# --- 4: rebrand visible strings + Terms URL ----------------------------------------------------

def _rebrand() -> None:
    edits = [
        (HOME_PATH,
         'self._openpilot_label = UnifiedLabel("sunnypilot", font_size=96',
         'self._openpilot_label = UnifiedLabel("MyPilot", font_size=96',
         'UnifiedLabel("MyPilot", font_size=96'),
        # Device screen is small and the "MyPilot" wordmark is right above this line, so show just
        # the MyPilot version (e.g. "2026.06.26-03") — drop the "sunnypilot-...-mypilot-" prefix.
        # The MyPilot version already encodes the date + a per-day build counter, so we BLANK the
        # separate "Jun 26" date label (it was redundant). The Version param is untouched, so the
        # dashboard still shows the complete version.
        (HOME_PATH,
         "    return version, branch, commit[:7], date_str",
         '    _disp = version.split("-mypilot-", 1)[1] if version and "-mypilot-" in version else version\n'
         '    return _disp, branch, commit[:7], ""  # date encoded in _disp; blank the redundant date label',
         '_disp = version.split("-mypilot-"'),
        (TOGGLES_PATH,
         'BigParamControl("enable sunnypilot", "OpenpilotEnabledToggle"',
         'BigParamControl("enable MyPilot", "OpenpilotEnabledToggle"',
         '"enable MyPilot"'),
        (FIREHOSE_PATH,
         '"sunnypilot learns to drive by watching humans, like you, drive.\\n\\n"',
         '"MyPilot learns to drive by watching humans, like you, drive.\\n\\n"',
         '"MyPilot learns to drive'),
        (ALERT_RENDERER_PATH,
         'text1="sunnypilot Unavailable"',
         'text1="MyPilot Unavailable"',
         '"MyPilot Unavailable"'),
        (OFFROAD_ALERTS_PATH,
         'version_string = f"\\nsunnypilot {version}, {date}\\n"',
         'version_string = f"\\nMyPilot {version}, {date}\\n"',
         '"\\nMyPilot {version}'),
        (SETUP_PATH,
         'self._download_failed_reason = "Incompatible sunnypilot version."',
         'self._download_failed_reason = "Incompatible MyPilot version."',
         '"Incompatible MyPilot version."'),
    ]
    for path, old, new, already in edits:
        _replace_once(path, old, new, already=already, what=f"rebrand {os.path.basename(path)}")

    # device.py has two identical "update sunnypilot" strings + one uninstall. Rebrand each
    # independently and idempotently (no shared sentinel, so a partial prior run can't leave one
    # half permanently un-rebranded — each replace re-runs until its own 'sunnypilot' form is gone).
    src = _read(DEVICE_PATH)
    orig = src
    if '"update sunnypilot"' in src:
        if src.count('"update sunnypilot"') != 2:
            raise AnchorError(f"rebrand device.py: expected 2 'update sunnypilot', found {src.count(chr(34)+'update sunnypilot'+chr(34))}")
        src = src.replace('"update sunnypilot"', '"update MyPilot"')
    if 'EngagedConfirmationButton("uninstall sunnypilot"' in src:
        src = src.replace('EngagedConfirmationButton("uninstall sunnypilot"',
                          'EngagedConfirmationButton("uninstall MyPilot"', 1)
    if src != orig:
        _write(DEVICE_PATH, src)
        print("[mypilot] rebrand device.py: patched")
    else:
        print("[mypilot] rebrand device.py: already applied")

    # augmented_road_view: two identical occurrences (init + reset).
    src = _read(ROAD_VIEW_PATH)
    if '"start the car to\\nuse MyPilot"' not in src:
        if src.count('"start the car to\\nuse sunnypilot"') != 2:
            raise AnchorError("rebrand augmented_road_view: expected 2 'use sunnypilot' occurrences")
        _write(ROAD_VIEW_PATH, src.replace('"start the car to\\nuse sunnypilot"', '"start the car to\\nuse MyPilot"'))
        print("[mypilot] rebrand augmented_road_view: patched")
    else:
        print("[mypilot] rebrand augmented_road_view: already applied")

    # mici onboarding free-text rebrands (each unique).
    for old, new, already in [
        ('GreyBigButton("", "sunnypilot uses the cabin camera to check if the driver is distracted."),',
         'GreyBigButton("", "MyPilot uses the cabin camera to check if the driver is distracted."),',
         '"MyPilot uses the cabin camera'),
        ('GreyBigButton("", "Sharing your data with comma helps improve openpilot and sunnypilot for everyone."),',
         'GreyBigButton("", "Sharing your data with comma helps improve openpilot and MyPilot for everyone."),',
         'improve openpilot and MyPilot'),
        ('GreyBigButton("what is sunnypilot?", "scroll to continue",',
         'GreyBigButton("what is MyPilot?", "scroll to continue",',
         '"what is MyPilot?"'),
        ('GreyBigButton("", "1. sunnypilot is a driver assistance system."),',
         'GreyBigButton("", "1. MyPilot is a driver assistance system."),',
         '"1. MyPilot is a driver assistance'),
        ('self._must_accept_card = GreyBigButton("", "You must accept the Terms of Service to use sunnypilot.")',
         'self._must_accept_card = GreyBigButton("", "You must accept the Terms of Service to use MyPilot.")',
         "to use MyPilot.\")"),
        ('GreyBigButton("swipe for QR code", "or go to https://sunnypilot.ai/terms",',
         'GreyBigButton("swipe for QR code", "or go to https://mypilot.me/terms",',
         "https://mypilot.me/terms\","),
        ('QRCodeWidget("https://sunnypilot.ai/terms"),',
         'QRCodeWidget("https://mypilot.me/terms"),',
         'QRCodeWidget("https://mypilot.me/terms")'),
    ]:
        _replace_once(ONBOARD_MICI_PATH, old, new, already=already, what="rebrand mici onboarding")

    # non-mici onboarding welcome/terms.
    _replace_once(
        ONBOARD_PATH,
        'self._title = Label(tr("Welcome to sunnypilot"), font_size=90',
        'self._title = Label(tr("Welcome to MyPilot"), font_size=90',
        already='tr("Welcome to MyPilot")', what="rebrand onboarding welcome")
    _replace_once(
        ONBOARD_PATH,
        'tr("You must accept the Terms of Service to use sunnypilot. Read the latest terms at https://sunnypilot.ai/terms before continuing.")',
        'tr("You must accept the Terms of Service to use MyPilot. Read the latest terms at https://mypilot.me/terms before continuing.")',
        already="https://mypilot.me/terms before", what="rebrand onboarding terms desc")
    _rebrand_translations()


# Translation catalogs (.po/.pot) override tr() at runtime, so a non-English device would otherwise
# still render the old "sunnypilot" onboarding/terms text and — worse — the wrong terms URL. Scrub
# the catalogs too. We target only the user-visible onboarding/terms strings (msgid AND msgstr) and
# the bad URL; we deliberately DO NOT touch `#:` source-path comments or community.sunnypilot.ai
# forum links. Fail-soft: localization is not safety-critical, so a missing catalog is just skipped.
TRANSLATIONS_DIR = "selfdrive/ui/translations"
_TRANSLATION_SUBS = [
    # the wrong external Terms URL — the important correctness fix for non-English devices
    ("https://sunnypilot.ai/terms", "https://mypilot.me/terms"),
    # standalone brand mentions in the onboarding/terms strings (leading-space / capitalized forms
    # are matched as whole tokens so we never hit community.sunnypilot.ai or path comments)
    ("Welcome to sunnypilot", "Welcome to MyPilot"),
    ("to use sunnypilot.", "to use MyPilot."),
    ("use sunnypilot. Read the latest terms", "use MyPilot. Read the latest terms"),
    ("sunnypilot Unavailable", "MyPilot Unavailable"),
]


def _rebrand_translations() -> None:
    if not os.path.isdir(TRANSLATIONS_DIR):
        print("[mypilot] translations dir not found; skipping catalog rebrand")
        return
    for name in sorted(os.listdir(TRANSLATIONS_DIR)):
        if not (name.endswith(".po") or name.endswith(".pot")):
            continue
        path = os.path.join(TRANSLATIONS_DIR, name)
        src = _read(path)
        new = src
        for old, repl in _TRANSLATION_SUBS:
            new = new.replace(old, repl)
        if new != src:
            _write(path, new)
            print(f"[mypilot] rebranded catalog {name}")


# --- 5: swap the mici sunnylink settings panel for MyPilot Link --------------------------------

def _swap_settings_panel() -> None:
    # The import rewire below and the vendored UI file are a coupled pair: if assemble.py didn't lay
    # down mypilot_link.py (renamed/missing files/ tree), rewiring the import would ship a tree that
    # imports a non-existent module. Assert the file is present BEFORE we rewire to it.
    link_module = "selfdrive/ui/sunnypilot/mici/layouts/mypilot_link.py"
    pair_module = "selfdrive/ui/sunnypilot/mici/widgets/mypilot_pairing_dialog.py"
    for m in (link_module, pair_module):
        if not os.path.exists(m):
            raise AnchorError(f"settings panel swap: vendored UI file missing: {m} "
                              "(assemble.py did not copy the base's files/ tree?)")
    _replace_once(
        SETTINGS_PATH,
        "from openpilot.selfdrive.ui.sunnypilot.mici.layouts.sunnylink import SunnylinkLayoutMici",
        "from openpilot.selfdrive.ui.sunnypilot.mici.layouts.mypilot_link import MyPilotLinkLayoutMici",
        already="import MyPilotLinkLayoutMici", what="settings import")
    _replace_once(
        SETTINGS_PATH,
        ('    sunnylink_panel = SunnylinkLayoutMici(back_callback=gui_app.pop_widget)\n'
         '    sunnylink_btn = SettingsBigButton(tr("sunnylink"), "", gui_app.texture("icons_mici/settings/developer/ssh.png", 55, 55))\n'
         '    sunnylink_btn.set_click_callback(lambda: gui_app.push_widget(sunnylink_panel))'),
        ('    mypilot_link_panel = MyPilotLinkLayoutMici(back_callback=gui_app.pop_widget)\n'
         '    mypilot_link_btn = SettingsBigButton(tr("MyPilot Link"), "", gui_app.texture("icons_mici/settings/developer/ssh.png", 55, 55))\n'
         '    mypilot_link_btn.set_click_callback(lambda: gui_app.push_widget(mypilot_link_panel))'),
        already="mypilot_link_panel = MyPilotLinkLayoutMici", what="settings panel")
    _replace_once(
        SETTINGS_PATH,
        "    items.insert(1, sunnylink_btn)",
        "    items.insert(1, mypilot_link_btn)",
        already="items.insert(1, mypilot_link_btn)", what="settings menu item")

    # The MyPilot Link UI files are vendored by assemble.py; the old sunnylink panel + dialog are now
    # dead. Delete them so a grep for sunnylink stays clean and nothing can re-wire to them.
    for path in (SUNNYLINK_PANEL, SUNNYLINK_DIALOG):
        if os.path.exists(path):
            os.remove(path)
            print("[mypilot] removed dead", path)


# --- 6: pairing alert --------------------------------------------------------------------------

def _register_pairing_alert() -> None:
    # alerts_offroad.json is a required upstream file the agent's on-screen pairing depends on. If it
    # is missing, an upstream move/rename happened — fail loud rather than silently shipping an agent
    # that references an unregistered alert key.
    if not os.path.exists(ALERTS_PATH):
        raise AnchorError(f"pairing alert: {ALERTS_PATH} not found (upstream moved it?)")
    with open(ALERTS_PATH) as fh:
        alerts = json.load(fh)
    if ALERT_KEY in alerts:
        print("[mypilot] pairing alert already registered")
        return
    alerts[ALERT_KEY] = ALERT_ENTRY
    with open(ALERTS_PATH, "w") as fh:
        json.dump(alerts, fh, indent=2)
        fh.write("\n")
    print("[mypilot] registered", ALERT_KEY, "in", ALERTS_PATH)


def _stamp_version() -> None:
    """Rebrand the version string to ``<tag>-<upstream-version>-mypilot-<base-date>-<NN>`` (e.g.
    ``sunnypilot-2026.002.000-mypilot-2026.06.26-18``) so it shows the base family + upstream version + a
    MyPilot marker + the snapshot date, instead of the bare upstream version. The date is the BASE
    COMMIT date (HEAD of the
    assembled tree before our edits land), so it changes only when the upstream base advances — no
    daily publish churn, reproducible. Idempotent: skipped if already tagged."""
    if not os.path.exists(VERSION_H):
        raise AnchorError(f"version stamp: {VERSION_H} not found (upstream moved it?)")
    src = _read(VERSION_H)
    m = re.search(r'#define\s+SUNNYPILOT_VERSION\s+"([^"]+)"', src)
    if not m:
        raise AnchorError(f"version stamp: SUNNYPILOT_VERSION not found in {VERSION_H}")
    cur = m.group(1)
    if cur.startswith(f"{BASE_TAG}-"):
        print("[mypilot] version: already stamped")
        return
    # MyPilot version date — auto-derived by assemble.py from the last commit that touched a
    # device-affecting path (passed in via env). It only changes when we ship device changes, so the
    # stamped version (and thus the published branch content) doesn't churn on every daily rebuild.
    mp = os.environ.get("MYPILOT_VERSION", "").strip()
    new_ver = f"{BASE_TAG}-{cur}-mypilot" + (f"-{mp}" if mp else "")
    _write(VERSION_H, src.replace(m.group(0), f'#define SUNNYPILOT_VERSION "{new_ver}"', 1))
    print(f"[mypilot] version: {cur} -> {new_ver}")


def main() -> int:
    try:
        _stamp_version()
        _register_process()
        _disable_sunnylink_daemons()
        _disable_sunnylink_ui()
        _rebrand()
        _swap_settings_panel()
        _register_pairing_alert()
    except AnchorError as exc:
        print(f"[mypilot] FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
