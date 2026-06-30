"""The app builds and serves with no extensions installed — the default for a clean checkout.

create_app() invites any package registered under the "mypilot.app" entry-point group to extend the
app (add routers, etc.); with none installed the loop is a no-op. This pins that the core stands on its
own and that the extension hook never breaks a plain install."""

from __future__ import annotations

from app.main import create_app


def test_app_builds_with_no_extensions():
    app = create_app()
    # The core API is present and the app is serveable as-is.
    paths = {r.path for r in app.routes}
    assert "/api/health" in paths
    assert any(p.startswith("/api/devices") for p in paths)
    assert any(p.startswith("/api/routes") for p in paths)
