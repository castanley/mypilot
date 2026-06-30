"""Device backends: a thorough simulated device, and the real openpilot-backed device (M9)."""

from .base import DeviceBackend
from .simulated import SimulatedDevice

__all__ = ["DeviceBackend", "SimulatedDevice", "make_backend"]


def make_backend(cfg, identity) -> DeviceBackend:
    """Select the device backend. Simulated by default; ``--real`` uses the on-device backend."""
    if getattr(cfg, "real", False):
        from .real import RealDevice

        return RealDevice(identity.hardware_id, identity.hostname)
    return SimulatedDevice(
        identity.hardware_id, identity.hostname, onroad=cfg.onroad, cycle=cfg.cycle
    )
