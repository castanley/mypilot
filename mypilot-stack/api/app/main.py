"""MyPilot API application factory."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from importlib.metadata import entry_points

from fastapi import FastAPI
from redis.asyncio import Redis

from . import storage
from .config import get_settings
from .realtime import ConnectionManager, run_event_subscriber
from .routers import (
    auth,
    backups as backups_router,
    device_self,
    devices,
    devtools,
    health,
    ingest,
    models as models_router,
    pairing,
    realtime,
    routes as routes_router,
    settings as settings_router,
    software as software_router,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mypilot.api")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Redis + connection manager may be pre-seeded by tests; otherwise create them.
    if getattr(app.state, "redis", None) is None:
        # retry_on_timeout + a periodic health check so a brief Redis blip retries transparently
        # instead of erroring straight into request handlers (presence/pub/sub/rate-limit all ride
        # this client). socket_keepalive keeps long-idle pub/sub connections from being silently dropped.
        app.state.redis = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            retry_on_timeout=True,
            health_check_interval=30,
            socket_keepalive=True,
        )
    if getattr(app.state, "manager", None) is None:
        app.state.manager = ConnectionManager()

    subscriber_task: asyncio.Task | None = None
    reaper_task: asyncio.Task | None = None
    if not settings.is_testing:
        try:
            await storage.ensure_bucket()
        except Exception:  # noqa: BLE001 - storage is non-critical for boot (used from M4)
            log.warning("object storage not ready at startup (will retry on use)")
        try:
            from .db import SessionLocal
            from .seed import seed_models, seed_releases, seed_settings

            async with SessionLocal() as session:
                count = await seed_settings(session)
                models = await seed_models(session)
                releases = await seed_releases(session)
            log.info("seeded %d settings, %d models, %d releases", count, models, releases)
        except Exception:  # noqa: BLE001
            log.warning("catalog seed skipped (db/storage not ready?)")
        subscriber_task = asyncio.create_task(run_event_subscriber(app))
        # Reconcile DB rows whose Redis presence expired with no clean disconnect (ungraceful drop /
        # wedged sim) -> clears stale onroad/driving + emits the presence:false event the client
        # trusts. The proactive half of the phantom-liveness defense.
        from .device_service import reap_expired_presence
        reaper_task = asyncio.create_task(reap_expired_presence(app.state.redis))

    try:
        yield
    finally:
        # Cancel any in-flight drive replays so each runs its park `finally` (clears the sim's
        # online/onroad) rather than being orphaned by a hard process exit.
        from . import replay_service
        active_replays = [t for t in replay_service._active.values() if not t.done()]
        for t in active_replays:
            t.cancel()
        if active_replays:
            await asyncio.gather(*active_replays, return_exceptions=True)
        for task in (reaper_task, subscriber_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if not settings.is_testing:
            await app.state.redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="MyPilot API",
        version="0.1.0",
        summary="Self-hosted control plane for MyPilot (auth, devices, pairing, realtime).",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        lifespan=lifespan,
    )
    app.state.redis = None
    app.state.manager = None

    # Order matters: literal-prefix routers before the generic /api/devices router.
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(pairing.router)
    app.include_router(device_self.router)
    app.include_router(ingest.router)
    app.include_router(settings_router.router)
    app.include_router(routes_router.router)
    app.include_router(models_router.router)
    app.include_router(software_router.router)
    app.include_router(backups_router.router)
    app.include_router(devtools.router)  # /api/admin/dev/* — before the generic /api/devices
    app.include_router(devices.router)
    app.include_router(realtime.router)

    # Extensions: any installed package that registers under the "mypilot.app" entry-point group gets
    # its setup(app) called once the core app is built — to add routers, background tasks, etc. A clean
    # install has none, so this is a no-op. (Standard Python plugin discovery, à la pytest/flake8.)
    for ep in entry_points(group="mypilot.app"):
        ep.load()(app)
    return app


app = create_app()
