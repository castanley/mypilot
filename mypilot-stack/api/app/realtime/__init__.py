"""Realtime layer: device + browser WebSockets, presence, and a Redis pub/sub fan-out."""

from .manager import ConnectionManager, run_event_subscriber

__all__ = ["ConnectionManager", "run_event_subscriber"]
