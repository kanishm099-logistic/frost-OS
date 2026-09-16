"""
Database Storage and Repository Layer.

SQLAlchemy Async ORM models & repository implementation for PostgreSQL / TimescaleDB / SQLite.
Persists optimization runs, input snapshots, decision variables, constraint definitions,
mission allocations, storage schedules, scenario results, and audit trails.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from sqlalchemy import String, Float, Boolean, Integer, Text, DateTime, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config.settings import Settings
from app.models.optimization_result import OptimizationResult


class Base(DeclarativeBase):
    """SQLAlchemy Declarative Base class."""
    pass


class OptimizationRunTable(Base):
    """DB model for optimization runs."""
    __tablename__ = "optimization_runs"

    optimization_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    station_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    horizon_minutes: Mapped[int] = mapped_column(Integer)
    time_step_minutes: Mapped[int] = mapped_column(Integer)
    solver_name: Mapped[str] = mapped_column(String(32))
    solver_status: Mapped[str] = mapped_column(String(32))
    objective_value: Mapped[float] = mapped_column(Float)
    feasible: Mapped[bool] = mapped_column(Boolean)
    validation_passed: Mapped[bool] = mapped_column(Boolean)
    scenario: Mapped[str] = mapped_column(String(64))
    result_json: Mapped[str] = mapped_column(Text)


class AuditLogTable(Base):
    """DB model for optimization audit logs."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    optimization_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    details_json: Mapped[str] = mapped_column(Text)


# Engine management globals
_async_engine = None
_async_session_factory = None


def init_engine(settings: Settings):
    """Initialize database engine."""
    global _async_engine, _async_session_factory
    _async_engine = create_async_engine(settings.database_url, echo=False)
    _async_session_factory = async_sessionmaker(_async_engine, expire_on_commit=False, class_=AsyncSession)


async def create_tables():
    """Create all tables in database."""
    if _async_engine:
        async with _async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def dispose_engine():
    """Close engine connections."""
    global _async_engine
    if _async_engine:
        await _async_engine.dispose()
        _async_engine = None


class OptimizationRepository:
    """Repository helper for async DB operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_run(self, result: OptimizationResult) -> None:
        """Save optimization run result to database."""
        row = OptimizationRunTable(
            optimization_id=result.optimization_id,
            station_id=result.station_id,
            horizon_minutes=result.horizon_minutes,
            time_step_minutes=result.time_step_minutes,
            solver_name=result.solver,
            solver_status=result.solver_status,
            objective_value=result.objective_value,
            feasible=result.feasible,
            validation_passed=result.validation_passed,
            scenario=result.scenario,
            result_json=result.model_dump_json(),
        )
        self.session.add(row)

        audit = AuditLogTable(
            optimization_id=result.optimization_id,
            event_type="OPTIMIZATION_COMPLETED",
            details_json=json.dumps({"feasible": result.feasible, "solver": result.solver}),
        )
        self.session.add(audit)
        await self.session.commit()

    async def get_run_by_id(self, opt_id: str) -> Optional[OptimizationResult]:
        """Retrieve run result by ID."""
        stmt = select(OptimizationRunTable).where(OptimizationRunTable.optimization_id == opt_id)
        res = await self.session.execute(stmt)
        row = res.scalar_one_or_none()
        if row and row.result_json:
            return OptimizationResult.model_validate_json(row.result_json)
        return None
