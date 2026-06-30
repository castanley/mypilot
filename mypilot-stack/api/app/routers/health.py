"""Health endpoints: public liveness/readiness and an authenticated admin view."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import fork_config, storage
from ..audit import record_audit
from ..db import get_session
from ..deps import CurrentAuth, client_ip, require_admin, require_admin_csrf
from ..models import AuditEvent
from ..schemas import (
    AuditEventOut,
    ForkConfig,
    ForkConfigUpdate,
    HealthComponent,
    HealthResponse,
    PublicSite,
)

router = APIRouter(tags=["health"])


def _fork_out(cfg: dict) -> ForkConfig:
    return ForkConfig(
        **cfg,
        release_install_url=fork_config.install_url_for("release", cfg),
        staging_install_url=fork_config.install_url_for("staging", cfg),
    )


async def _db_usage(db: AsyncSession) -> dict | None:
    """Best-effort database stats: on-disk size (Postgres) + a couple of headline row counts. Returns
    None on anything unexpected (e.g. SQLite in tests, or a permission error) so it never affects the
    health verdict."""
    try:
        usage: dict = {}
        if db.bind.dialect.name == "postgresql":
            size = (await db.execute(text("SELECT pg_database_size(current_database())"))).scalar()
            if size is not None:
                usage["size_bytes"] = int(size)
        devices = (await db.execute(text("SELECT count(*) FROM devices"))).scalar()
        routes = (await db.execute(text("SELECT count(*) FROM routes"))).scalar()
        usage["devices"] = int(devices or 0)
        usage["routes"] = int(routes or 0)
        return usage or None
    except Exception:  # noqa: BLE001 - stats are cosmetic; never break health
        return None


async def _redis_usage(redis) -> dict | None:
    """Best-effort Redis stats: memory used + key count. None on error."""
    try:
        info = await redis.info("memory")
        keys = await redis.dbsize()
        usage: dict = {"keys": int(keys)}
        used = info.get("used_memory") if isinstance(info, dict) else None
        if used is not None:
            usage["used_bytes"] = int(used)
        return usage
    except Exception:  # noqa: BLE001
        return None


async def _gather_health(request: Request, db: AsyncSession, *, with_usage: bool) -> HealthResponse:
    """Component liveness. ``with_usage`` controls whether the deployment-wide stats (DB size +
    device/route counts, Redis memory/keys, bucket bytes/object-count) are included. The
    unauthenticated /api/health probe passes False — it returns only component up/down, never the
    deployment totals. Only the admin-gated /api/admin/health asks for usage."""
    components: dict[str, HealthComponent] = {}

    try:
        await db.execute(text("SELECT 1"))
        components["database"] = HealthComponent(ok=True, usage=await _db_usage(db) if with_usage else None)
    except Exception as exc:  # noqa: BLE001
        components["database"] = HealthComponent(ok=False, detail=str(exc))

    try:
        redis = request.app.state.redis
        await redis.ping()
        components["redis"] = HealthComponent(ok=True, usage=await _redis_usage(redis) if with_usage else None)
    except Exception as exc:  # noqa: BLE001
        components["redis"] = HealthComponent(ok=False, detail=str(exc))

    ok, detail = await storage.check()
    # Bucket usage (best-effort: None if the listing fails, never blocks the health check) — admin-only.
    usage = (await storage.usage()) if (ok and with_usage) else None
    components["object_storage"] = HealthComponent(ok=ok, detail=detail, usage=usage)

    overall = all(c.ok for c in components.values())
    return HealthResponse(ok=overall, components=components)


@router.get("/api/health", response_model=HealthResponse)
async def health(request: Request, db: AsyncSession = Depends(get_session)) -> HealthResponse:
    # Unauthenticated liveness probe — component ok/down only, NO platform-wide usage stats.
    return await _gather_health(request, db, with_usage=False)


@router.get("/api/public/site", response_model=PublicSite)
async def public_site(db: AsyncSession = Depends(get_session)) -> PublicSite:
    """Public (no-auth) branding for the landing page — non-sensitive fields only."""
    cfg = await fork_config.get_fork_config(db)
    return PublicSite(**{k: cfg.get(k, "") for k in fork_config.PUBLIC_KEYS})


# /api/admin/* is the admin surface (site health, the audit log, fork/stack config). These are
# admin-only — a non-admin authenticated user must not read deployment-wide health or the audit log.
@router.get("/api/admin/health", response_model=HealthResponse)
async def admin_health(
    request: Request,
    db: AsyncSession = Depends(get_session),
    _auth: CurrentAuth = Depends(require_admin),
) -> HealthResponse:
    return await _gather_health(request, db, with_usage=True)


@router.get("/api/admin/audit", response_model=list[AuditEventOut])
async def admin_audit(
    db: AsyncSession = Depends(get_session),
    _auth: CurrentAuth = Depends(require_admin),
    limit: int = 100,
) -> list[AuditEventOut]:
    rows = (
        await db.execute(
            select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(min(limit, 500))
        )
    ).scalars().all()
    return [AuditEventOut.model_validate(r) for r in rows]


@router.get("/api/admin/config", response_model=ForkConfig)
async def get_config(
    db: AsyncSession = Depends(get_session),
    _auth: CurrentAuth = Depends(require_admin),
) -> ForkConfig:
    return _fork_out(await fork_config.get_fork_config(db))


@router.patch("/api/admin/config", response_model=ForkConfig)
async def update_config(
    payload: ForkConfigUpdate,
    request: Request,
    auth: CurrentAuth = Depends(require_admin_csrf),
    db: AsyncSession = Depends(get_session),
) -> ForkConfig:
    # PATCH (not PUT): a partial field-merge — only the keys present in the payload are updated
    # (model_dump(exclude_none=True)), omitted fields are left as-is. (Contrast PUT /api/retention,
    # which is a true full-replace.)
    cfg = await fork_config.set_fork_config(db, payload.model_dump(exclude_none=True))
    await record_audit(
        db, action="admin.config.update", actor_type="user", actor_id=str(auth.user.id),
        metadata={k: cfg[k] for k in ("stack_url", "github_owner", "release_branch", "staging_branch")},
        ip=client_ip(request),
    )
    await db.commit()
    return _fork_out(cfg)
