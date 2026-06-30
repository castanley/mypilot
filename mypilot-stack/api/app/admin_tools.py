"""Admin tools registry — a generic, extensible list of admin-only utility pages.

The web Admin hub (/admin) renders whatever tools are registered here. The core registers nothing by
default; an installed extension can register its own admin tool at startup so it shows up in the hub
(and gets an admin-only sidebar entry) without the web bundle knowing about it. Same spirit as the
mypilot.app plugin hook: a generic registry that reveals nothing about which specific tools exist.

A tool is a small descriptor: a stable `key`, a display `label`, the `href` its page lives at, and an
icon name. `GET /api/admin/tools` returns the registered set (admin-only) for the hub to render.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdminTool:
    key: str          # stable id, e.g. "metrics"
    label: str        # display name, e.g. "Metrics"
    href: str         # where its page lives, e.g. "/admin/metrics"
    description: str = ""
    icon: str = "sparkles"  # an icon name for the web hub; unknown names fall back gracefully

    def as_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "href": self.href,
                "description": self.description, "icon": self.icon}


_TOOLS: dict[str, AdminTool] = {}


def register(tool: AdminTool) -> None:
    """Register (or replace) an admin tool. Idempotent on key; safe to call at extension setup()."""
    _TOOLS[tool.key] = tool


def registered() -> list[AdminTool]:
    """The registered tools, sorted by label for a stable hub ordering."""
    return sorted(_TOOLS.values(), key=lambda t: t.label.lower())
