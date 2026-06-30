"""Backend abstraction so the agent's pairing/transport code is identical for the simulated
device today and a real openpilot-backed device later."""

from __future__ import annotations

from abc import ABC, abstractmethod


class DeviceBackend(ABC):
    """A source of device status and a sink for commands/settings.

    Implementations MUST NOT couple to or interfere with driving-critical processes, and MUST
    refuse any command or setting that could affect active driving while onroad.
    """

    hardware_id: str
    hostname: str

    @property
    @abstractmethod
    def onroad(self) -> bool:
        ...

    @abstractmethod
    def status(self) -> dict:
        """Return a status snapshot as the telemetry envelope (see mypilot_protocol.telemetry):
        ``{captured_at, onroad, subsystems{...}}``."""

    @abstractmethod
    async def execute(self, name: str, args: dict) -> tuple[bool, str]:
        """Execute a command (one of mypilot_protocol.messages.CommandName) and return
        (ok, human-readable detail). State-changing commands must be refused while onroad."""

    @abstractmethod
    def settings_sync_payload(self) -> dict:
        """Return ``{"capabilities": {...}, "values": {...}}`` for the settings panel."""

    @abstractmethod
    def apply_setting(self, key: str, value) -> tuple[bool, str]:
        """Apply one setting (offroad-gated); return (ok, detail)."""

    def attach_http(self, client) -> None:
        """Receive a signed HTTP client (artifact upload + model download). Optional."""

    def show_pairing_code(self, code: str, expires_at: str | None = None) -> None:
        """Surface the pairing code to the user (on-device this shows on the home screen)."""

    def clear_pairing_code(self) -> None:
        """Clear the on-screen pairing prompt once paired."""

    def generate_artifacts(self) -> tuple[list, list]:
        """Return ``(routes, logs)`` to backfill. Default: nothing."""
        return [], []

    async def run_state_cycler(self) -> None:
        """Optional background task to vary state (simulated only)."""
        return None
