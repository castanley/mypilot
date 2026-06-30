"""WebSocket frame types, command names, and challenge constructors shared by both sides.

Frames are JSON objects with a ``type`` field drawn from :class:`FrameType`. Keeping these
constants in one shared place prevents the agent and the Stack from drifting apart.
"""

from __future__ import annotations

from enum import Enum


class FrameType(str, Enum):
    # Device WebSocket handshake
    AUTH_CHALLENGE = "auth_challenge"   # server -> device: {nonce}
    AUTH = "auth"                       # device -> server: {device_id, signature}
    AUTH_OK = "auth_ok"                 # server -> device: {device_id}
    AUTH_FAIL = "auth_fail"             # server -> device: {reason}

    # Telemetry
    HEARTBEAT = "heartbeat"             # device -> server: liveness (refreshes presence)
    STATUS = "status"                   # device -> server: full status payload

    # Commands
    COMMAND = "command"                 # server -> device: {id, name, args}
    COMMAND_RESULT = "command_result"   # device -> server: {id, ok, detail}

    # Settings (M3)
    SETTINGS_SYNC = "settings_sync"     # device -> server: {capabilities, values}
    SET_SETTING = "set_setting"         # server -> device: {change_id, key, value}
    SETTING_RESULT = "setting_result"   # device -> server: {change_id, key, ok, value, detail}

    # Fan-out to browsers (web WebSocket)
    PRESENCE = "presence"               # server -> web: {device_id, online}
    DEVICE_STATUS = "device_status"     # server -> web: {device_id, status}
    DEVICE_EVENT = "device_event"       # server -> web: {device_id, event, ...}

    ERROR = "error"


class CommandName(str, Enum):
    """Commands the Stack can send to a device. New commands are added per milestone."""

    REBOOT = "reboot"                    # offroad-only, confirmed, audited
    SWITCH_MODEL = "switch_model"        # M5: offroad-only; device verifies checksum then activates
    SOFTWARE_UPDATE = "software_update"  # M7: offroad-only; device installs target version/channel
    RESTORE_SETTINGS = "restore_settings"  # M6: device re-applies a settings backup (offroad-gated)


# --- Challenge constructors (signed to prove possession of the device private key) ----------

def pairing_challenge(pairing_id: str) -> bytes:
    """Challenge signed by the device in POST /api/devices/register/complete."""
    return f"mypilot-pair:{pairing_id}".encode("utf-8")


def ws_auth_message(nonce: str) -> bytes:
    """Challenge signed by the device during the realtime WebSocket handshake."""
    return f"mypilot-ws:{nonce}".encode("utf-8")
