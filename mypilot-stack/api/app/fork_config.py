"""Fork / deployment configuration (stored in SystemConfig under key ``fork``).

MyPilot is meant to be forked and self-hosted. Rather than hard-coding the public Stack URL or the
GitHub fork/branch into the code, they live here and are editable from the Settings page. Install
URLs shown across the UI + sent to devices are **derived** from this config, so a forker only
changes these values (no code edits).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .models import SystemConfig

KEY = "fork"

DEFAULTS: dict[str, str] = {
    # Branding / public site — override per deployment.
    "project_name": "MyPilot",
    "stack_url": "",   # your deployment's public URL (shown on the landing if set)
    "source_url": "",  # link to your source repo (shown on the landing if set)
    # Install source (drives every install URL) — point these at your own openpilot fork + branches.
    "installer_base": "https://installer.comma.ai",
    "github_owner": "",
    "release_branch": "",
    "staging_branch": "",
}

# The non-sensitive subset exposed publicly (landing page).
PUBLIC_KEYS = ("project_name", "stack_url", "source_url")


async def get_fork_config(db: AsyncSession) -> dict:
    row = await db.get(SystemConfig, KEY)
    cfg = dict(DEFAULTS)
    if row is not None and isinstance(row.value, dict):
        cfg.update({k: v for k, v in row.value.items() if k in DEFAULTS and v})
    return cfg


async def set_fork_config(db: AsyncSession, values: dict) -> dict:
    cfg = await get_fork_config(db)
    cfg.update({k: v for k, v in values.items() if k in DEFAULTS and v})
    row = await db.get(SystemConfig, KEY)
    if row is None:
        db.add(SystemConfig(key=KEY, value=cfg))
    else:
        row.value = cfg
    return cfg


def branch_for(channel: str, cfg: dict) -> str:
    return cfg["staging_branch"] if channel == "staging" else cfg["release_branch"]


def install_url_for(channel: str, cfg: dict) -> str:
    base = cfg["installer_base"].rstrip("/")
    return f"{base}/{cfg['github_owner']}/{branch_for(channel, cfg)}"
