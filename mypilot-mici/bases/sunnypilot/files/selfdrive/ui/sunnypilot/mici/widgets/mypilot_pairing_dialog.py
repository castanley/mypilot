"""MyPilot device pairing dialog (QR + PIN) for the mici UI.

Replaces the sunnylink pairing flow. The MyPilot agent (mypilotd) talks to the self-hosted Stack
(mypilot.me), obtains a one-time pairing code, and writes it to ``/data/mypilot/pairing.json`` (a
plain file — on a prebuilt branch we can't declare a Params key for it). This dialog reads that file
and renders:

  * a QR code encoding ``https://mypilot.me/devices/pair?code=<PIN>`` so a phone scan opens the web
    pair page with the code prefilled, and
  * the human-enterable PIN below it.

No SSH, no comma connect, no sunnylink. Mirrors the structure of the comma ``PairingDialog`` so it
behaves identically (5-minute refresh, texture lifecycle).
"""

import json
import os
import time

import numpy as np
import pyray as rl
import qrcode

from openpilot.common.swaglog import cloudlog
from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.widgets.label import UnifiedLabel
from openpilot.system.ui.widgets.nav_widget import NavWidget

PAIRING_FILE = "/data/mypilot/pairing.json"


class MyPilotPairingDialog(NavWidget):
  """Dialog for MyPilot device pairing with a QR code + PIN."""

  REFRESH_INTERVAL = 5  # seconds; the agent rotates the code, so re-read the file often

  def __init__(self):
    super().__init__()
    self._qr_texture: rl.Texture | None = None
    self._code: str = ""
    self._url: str = ""
    self._last_refresh = float("-inf")

    self._title_label = UnifiedLabel("pair with MyPilot", font_size=40, font_weight=FontWeight.BOLD, line_height=0.8)
    # The 8-char PIN sits in a narrow column beside the square QR. Keep it on ONE line: smaller font
    # + wrap_text=False so two characters can't spill to a second row.
    self._code_label = UnifiedLabel("", font_size=44, font_weight=FontWeight.DISPLAY, line_height=0.8,
                                    wrap_text=False)
    # Use ASCII '>' as the separator: the device UI font has no right-arrow glyph (rendered as '?').
    self._hint_label = UnifiedLabel("Web > Devices > Pair device", font_size=28,
                                    font_weight=FontWeight.ROMAN, line_height=0.9, wrap_text=False)

  def _read_pairing(self) -> tuple[str, str]:
    try:
      with open(PAIRING_FILE) as fh:
        data = json.load(fh) or {}
      return data.get("code") or "", data.get("url") or ""
    except Exception:  # noqa: BLE001 - file may not exist yet (agent still pairing / disabled)
      return "", ""

  def _generate_qr_code(self, url: str) -> None:
    try:
      qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=0)
      qr.add_data(url)
      qr.make(fit=True)

      pil_img = qr.make_image(fill_color="white", back_color="black").convert('RGBA')
      img_array = np.array(pil_img, dtype=np.uint8)

      if self._qr_texture and self._qr_texture.id != 0:
        rl.unload_texture(self._qr_texture)

      rl_image = rl.Image()
      rl_image.data = rl.ffi.cast("void *", img_array.ctypes.data)
      rl_image.width = pil_img.width
      rl_image.height = pil_img.height
      rl_image.mipmaps = 1
      rl_image.format = rl.PixelFormat.PIXELFORMAT_UNCOMPRESSED_R8G8B8A8

      self._qr_texture = rl.load_texture_from_image(rl_image)
    except Exception as e:  # noqa: BLE001
      cloudlog.warning(f"MyPilot QR code generation failed: {e}")
      self._qr_texture = None

  def _check_refresh(self) -> None:
    current_time = time.monotonic()
    if current_time - self._last_refresh < self.REFRESH_INTERVAL:
      return
    self._last_refresh = current_time
    code, url = self._read_pairing()
    if code != self._code or url != self._url:
      self._code, self._url = code, url
      self._code_label.set_text(code or "waiting for code...")
      if url:
        self._generate_qr_code(url)
      else:
        if self._qr_texture and self._qr_texture.id != 0:
          rl.unload_texture(self._qr_texture)
        self._qr_texture = None

  def _update_state(self):
    super()._update_state()
    # Auto-dismiss once pairing completes: the agent clears pairing.json and writes device_id into
    # identity.json. Mirrors the comma PairingDialog dismissing when prime_state.is_paired().
    if self._code and not self.is_dismissing:
      try:
        import os as _os
        if not _os.path.exists(PAIRING_FILE):
          with open(_os.path.join(_os.path.dirname(PAIRING_FILE), "identity.json")) as fh:
            if (json.load(fh) or {}).get("device_id"):
              self.dismiss()
      except Exception:  # noqa: BLE001
        pass

  def _render(self, rect: rl.Rectangle):
    self._check_refresh()

    # QR on the left (square, full height), text column to the right.
    self._render_qr_code()

    label_x = self._rect.x + 8 + self._rect.height + 24
    max_w = int(self._rect.width - label_x)

    # Stack the three labels with clear vertical gaps so the PIN never overlaps the title and the
    # hint never falls off the bottom. Positions are relative to the rect top, sized to the rect
    # height (the QR is the full-height square on the left).
    self._title_label.set_max_width(max_w)
    self._title_label.set_position(label_x, self._rect.y + 10)
    self._title_label.render()

    self._code_label.set_max_width(max_w)
    self._code_label.set_position(label_x, self._rect.y + int(self._rect.height * 0.40))
    self._code_label.render()

    self._hint_label.set_max_width(max_w)
    self._hint_label.set_position(label_x, self._rect.y + self._rect.height - 40)
    self._hint_label.render()

  def _render_qr_code(self) -> None:
    if not self._qr_texture:
      font = gui_app.font(FontWeight.BOLD)
      msg = "waiting for code..."
      rl.draw_text_ex(font, msg, rl.Vector2(self._rect.x + 20, self._rect.y + self._rect.height // 2 - 15),
                      30, 0.0, rl.Color(255, 255, 255, int(255 * 0.5)))
      return

    scale = self._rect.height / self._qr_texture.height
    pos = rl.Vector2(round(self._rect.x + 8), round(self._rect.y))
    rl.draw_texture_ex(self._qr_texture, pos, 0.0, scale, rl.WHITE)

  def __del__(self):
    tex = getattr(self, "_qr_texture", None)
    if tex and tex.id != 0:
      rl.unload_texture(tex)


if __name__ == "__main__":
  gui_app.init_window("mypilot pairing")
  dlg = MyPilotPairingDialog()
  gui_app.push_widget(dlg)
  try:
    for _ in gui_app.render():
      pass
  finally:
    del dlg
