"""Agent configuration from environment + CLI flags."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass


@dataclass
class AgentConfig:
    stack_url: str
    data_dir: str
    alias: str
    onroad: bool
    cycle: bool
    hardware_id: str | None
    reset: bool
    real: bool = False

    @property
    def api_base(self) -> str:
        return self.stack_url.rstrip("/")

    @property
    def ws_url(self) -> str:
        base = self.api_base
        if base.startswith("https://"):
            return "wss://" + base[len("https://") :] + "/api/realtime/device"
        if base.startswith("http://"):
            return "ws://" + base[len("http://") :] + "/api/realtime/device"
        return base + "/api/realtime/device"


def parse_config(argv: list[str] | None = None) -> AgentConfig:
    parser = argparse.ArgumentParser(
        prog="mypilot-agent",
        description="MyPilot device agent (simulated device for M1/M2).",
    )
    parser.add_argument(
        "--stack-url",
        default=os.environ.get("MYPILOT_STACK_URL", "http://localhost"),
        help="Base URL of the MyPilot Stack (default: env MYPILOT_STACK_URL or http://localhost)",
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("MYPILOT_AGENT_DATA_DIR", os.path.expanduser("~/.mypilot/agent")),
        help="Directory for the device identity/key material.",
    )
    parser.add_argument(
        "--alias",
        default=os.environ.get("MYPILOT_SIM_ALIAS", "Simulated comma three"),
        help="Suggested device alias (used if the user does not set one when claiming).",
    )
    parser.add_argument("--onroad", action="store_true", help="Start in the onroad state.")
    parser.add_argument(
        "--cycle",
        action="store_true",
        help="Periodically toggle onroad/offroad to demonstrate state changes.",
    )
    parser.add_argument("--hardware-id", default=os.environ.get("MYPILOT_HARDWARE_ID"))
    parser.add_argument(
        "--reset", action="store_true", help="Forget the stored identity and pair again."
    )
    parser.add_argument(
        "--real",
        action="store_true",
        default=os.environ.get("MYPILOT_AGENT_REAL") == "1",
        help="Use the real on-device backend (openpilot/SunnyPilot) instead of the simulator.",
    )
    args = parser.parse_args(argv)
    return AgentConfig(
        stack_url=args.stack_url,
        data_dir=args.data_dir,
        alias=args.alias,
        onroad=args.onroad,
        cycle=args.cycle,
        hardware_id=args.hardware_id,
        reset=args.reset,
        real=args.real,
    )
