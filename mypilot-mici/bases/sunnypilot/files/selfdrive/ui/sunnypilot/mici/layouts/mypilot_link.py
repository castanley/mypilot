"""MyPilot Link settings panel for the mici UI.

Replaces the sunnylink panel. MyPilot is the self-hosted control plane (mypilot.me); this panel
lets the user:

  * toggle "MyPilot Link" on/off — this gates the on-device agent (mypilotd). The agent reads its
    enable flag from ``/data/mypilot/config.json`` (key ``enabled``), so the toggle writes that
    file. No Params key is involved (can't declare one on a prebuilt branch).
  * once enabled, tap "Pair" to open the MyPilot Pair screen (QR code + PIN).

Nothing here talks to sunnylink or comma connect.
"""

import json
import os
import time

from collections.abc import Callable

from openpilot.selfdrive.ui.mici.widgets.button import BigButton, BigToggle
from openpilot.selfdrive.ui.mici.widgets.dialog import BigDialog
from openpilot.selfdrive.ui.sunnypilot.mici.widgets.mypilot_pairing_dialog import MyPilotPairingDialog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.scroller import NavScroller

import pyray as rl

MYPILOT_DIR = "/data/mypilot"
CONFIG_PATH = os.path.join(MYPILOT_DIR, "config.json")
PAIRING_FILE = os.path.join(MYPILOT_DIR, "pairing.json")
DEFAULT_STACK_URL = "https://mypilot.me"


def _read_config() -> dict:
  try:
    with open(CONFIG_PATH) as fh:
      return json.load(fh) or {}
  except Exception:  # noqa: BLE001
    return {}


def _link_enabled() -> bool:
  # Default True: a fresh build pairs out of the box, matching the agent's own default.
  return bool(_read_config().get("enabled", True))


def _set_link_enabled(enabled: bool) -> None:
  cfg = _read_config()
  cfg["enabled"] = enabled
  cfg.setdefault("stack_url", DEFAULT_STACK_URL)
  try:
    os.makedirs(MYPILOT_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w") as fh:
      json.dump(cfg, fh, indent=2)
    os.replace(tmp, CONFIG_PATH)
  except Exception:  # noqa: BLE001
    pass


def _is_paired() -> bool:
  try:
    with open(os.path.join(MYPILOT_DIR, "identity.json")) as fh:
      return bool((json.load(fh) or {}).get("device_id"))
  except Exception:  # noqa: BLE001
    return False


class MyPilotLinkInfo(Widget):
  def __init__(self):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 360, 180))
    header_color = rl.Color(255, 255, 255, int(255 * 0.9))
    sub_color = rl.Color(255, 255, 255, int(255 * 0.9 * 0.65))
    max_width = int(self._rect.width - 20)
    self.stack_header = UnifiedLabel(tr("stack"), 48, max_width=max_width, text_color=header_color,
                                     font_weight=FontWeight.DISPLAY, shimmer=True)
    self.stack_text = UnifiedLabel(DEFAULT_STACK_URL, 32, max_width=max_width, text_color=sub_color,
                                   font_weight=FontWeight.ROMAN, scroll=True)
    self.status_header = UnifiedLabel(tr("status"), 48, max_width=max_width, text_color=header_color,
                                      font_weight=FontWeight.DISPLAY, shimmer=True)
    self.status_text = UnifiedLabel("—", 32, max_width=max_width, text_color=sub_color, font_weight=FontWeight.ROMAN)

  def _render(self, _):
    self.stack_header.set_position(self._rect.x + 20, self._rect.y - 10)
    self.stack_header.render()
    self.stack_text.set_position(self._rect.x + 20, self._rect.y + 68 - 25)
    self.stack_text.render()
    self.status_header.set_position(self._rect.x + 20, self._rect.y + 114 - 30)
    self.status_header.render()
    self.status_text.set_position(self._rect.x + 20, self._rect.y + 161 - 25)
    self.status_text.render()


class MyPilotLinkLayoutMici(NavScroller):
  def __init__(self, back_callback: Callable):
    super().__init__()
    self.set_back_callback(back_callback)

    self._last_poll = float("-inf")
    self._info = MyPilotLinkInfo()
    self._link_toggle = BigToggle(text=tr("enable MyPilot Link"),
                                  initial_state=_link_enabled(),
                                  toggle_callback=self._link_toggle_callback)
    self._pair_button = BigButton(tr("pair"), "")
    self._pair_button.set_click_callback(self._handle_pair)

    self._scroller.add_widgets([
      self._info,
      self._link_toggle,
      self._pair_button,
    ])

  def _update_state(self):
    super()._update_state()
    # _update_state runs every frame (60fps). Throttle the disk reads (config.json + identity.json)
    # to ~1Hz so the panel never hitches the always-on ui process on per-frame blocking I/O.
    now = time.monotonic()
    if now - self._last_poll < 1.0:
      return
    self._last_poll = now

    cfg = _read_config()
    enabled = bool(cfg.get("enabled", True))
    self._link_toggle.set_checked(enabled)
    self._pair_button.set_visible(enabled)
    self._info.set_visible(enabled)
    self._info.stack_text.set_text(cfg.get("stack_url", DEFAULT_STACK_URL))
    if not enabled:
      self._info.status_text.set_text(tr("off"))
      self._pair_button.set_text(tr("pair"))
    elif _is_paired():
      self._info.status_text.set_text(tr("paired"))
      self._pair_button.set_text(tr("paired"))
    else:
      self._info.status_text.set_text(tr("not paired"))
      self._pair_button.set_text(tr("pair"))

  @staticmethod
  def _link_toggle_callback(state: bool):
    _set_link_enabled(state)

  def _handle_pair(self):
    network_type = ui_state.sm["deviceState"].networkType
    if network_type == 0:
      gui_app.push_widget(BigDialog(tr("no internet"), tr("please connect to WiFi & try again")))
      return
    gui_app.push_widget(MyPilotPairingDialog())
