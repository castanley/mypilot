"""Async SQLAlchemy engine, session factory, and declarative base."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()


def _engine_kwargs() -> dict:
    """Engine kwargs. SQLite (tests) ignores pool sizing, so only pass it for a real server DB —
    and attach a statement_timeout via asyncpg's server_settings so a wedged query frees its
    connection instead of pinning the (now explicitly bounded) pool."""
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if _settings.database_url.startswith("postgresql"):
        kwargs.update(
            pool_size=_settings.db_pool_size,
            max_overflow=_settings.db_max_overflow,
            pool_timeout=_settings.db_pool_timeout_seconds,
        )
        if _settings.db_statement_timeout_ms > 0:
            kwargs["connect_args"] = {
                "server_settings": {"statement_timeout": str(_settings.db_statement_timeout_ms)}
            }
    return kwargs


# Engine creation is lazy (no connection is opened until first use), so importing this
# module never requires a reachable database.
engine = create_async_engine(_settings.database_url, **_engine_kwargs())

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields a request-scoped async session."""
    async with SessionLocal() as session:
        yield session
