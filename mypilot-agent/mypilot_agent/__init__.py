"""MyPilot Agent — the device-side client that pairs with and reports to the MyPilot Stack.

For Milestones 1-2 the agent runs against a :class:`SimulatedDevice` backend so the entire
control plane can be exercised without real hardware. The same agent will later drive a
:class:`RealDevice` backend (Milestone 9) — it is intentionally decoupled from any
driving-critical process and never controls driving.
"""

__version__ = "0.1.0"
