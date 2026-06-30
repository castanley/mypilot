"""Entry point: ``python -m mypilot_agent``."""

from __future__ import annotations

import asyncio

from .config import parse_config
from .runner import run


def main() -> None:
    cfg = parse_config()
    try:
        asyncio.run(run(cfg))
    except KeyboardInterrupt:
        print("\n[agent] stopped.")


if __name__ == "__main__":
    main()
