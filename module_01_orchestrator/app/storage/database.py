"""
Frost OS Module 01 — Database Engine & Session Factory.

Provides async SQLAlchemy engine, session factory, and table creation.
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

from app.config.settings import Settings

logger = structlog.get_logger(__name__)

# Module-level singletons (set during app startup)
_engine = None
_session_factory = None


def init_engine(settings: Settings):
    """Initialize the async database engine and session factory."""
    global _engine, _session_factory

    _engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def create_tables() -> None:
    """Create all database tables from ORM metadata."""
    from app.models.event import Base  # noqa: F811 — import for side-effect

    # Ensure all models are imported so metadata is populated
    import app.models.decision  # noqa: F401
    import app.models.action_plan  # noqa: F401

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await logger.ainfo("Database tables created")


async def drop_tables() -> None:
    """Drop all database tables (use with caution)."""
    from app.models.event import Base

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
    """Dispose of the database engine during shutdown."""
    global _engine
    if _engine:
        await _engine.dispose()
        await logger.ainfo("Database engine disposed")
