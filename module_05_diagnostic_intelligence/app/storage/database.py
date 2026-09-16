"""
Frost OS Module 05 — Database Engine & Session Factory.

Provides async SQLAlchemy engine, transactional session generator,
and table lifecycle management for diagnostic data persistence.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
import structlog

logger = structlog.get_logger(__name__)

# Module-level singletons
_engine = None
_session_factory = None


def init_engine(settings) -> None:
    """Initialize the async database engine and session factory."""
    global _engine, _session_factory

    is_sqlite = settings.database_url.startswith("sqlite")
    engine_kwargs = {"echo": settings.debug}

    if not is_sqlite:
        engine_kwargs.update({
            "pool_size": 10,
            "max_overflow": 20,
            "pool_pre_ping": True,
        })

    _engine = create_async_engine(settings.database_url, **engine_kwargs)

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def create_tables() -> None:
    """Create all database tables from ORM metadata."""
    from app.models.equipment import Base
    # Ensure all ORM models are imported so tables are registered
    import app.models.anomaly  # noqa: F401
    import app.models.health  # noqa: F401
    import app.models.fault  # noqa: F401
    import app.models.risk  # noqa: F401

    if _engine is None:
        raise RuntimeError("Engine not initialized. Call init_engine() first.")

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await logger.ainfo("Diagnostic Intelligence database tables created")


async def drop_tables() -> None:
    """Drop all database tables (for testing/reset)."""
    from app.models.equipment import Base
    import app.models.anomaly  # noqa: F401
    import app.models.health  # noqa: F401
    import app.models.fault  # noqa: F401
    import app.models.risk  # noqa: F401

    if _engine is None:
        return

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional async database session."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_engine() first.")

    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for database sessions."""
    async with get_session() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose database engine during shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        await logger.ainfo("Diagnostic database engine disposed")
