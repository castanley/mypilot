"""Example MyPilot extension — a Prometheus-style metrics endpoint.

This package exists to demonstrate the one extension point the MyPilot API exposes: a callable
registered under the ``mypilot.app`` entry-point group. At startup the API enumerates that group and
calls each ``setup(app)`` with the FastAPI application, after the core routes are mounted. An
extension can mount routers, add middleware, or register startup/shutdown hooks — anything you can do
with a FastAPI ``app``.

Install it (``pip install -e examples/mypilot-metrics-plugin``) alongside the API and ``GET
/api/metrics`` starts returning Prometheus text. Uninstall it and the route is simply gone; the core
app neither knows nor cares whether it is present.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Response

# Process start, captured at import. Exposed as a process_uptime_seconds gauge so the example emits
# something non-trivial without reaching into the app's database or Redis.
_STARTED_AT = time.monotonic()


def _render() -> str:
    uptime = time.monotonic() - _STARTED_AT
    lines = [
        "# HELP mypilot_process_uptime_seconds Seconds since this API process started.",
        "# TYPE mypilot_process_uptime_seconds gauge",
        f"mypilot_process_uptime_seconds {uptime:.3f}",
    ]
    return "\n".join(lines) + "\n"


def setup(app: FastAPI) -> None:
    """Entry point called by the MyPilot API at startup with the FastAPI app."""

    @app.get("/api/metrics", include_in_schema=False)
    async def metrics() -> Response:  # noqa: D401 - simple endpoint
        return Response(content=_render(), media_type="text/plain; version=0.0.4")
