"""
Async SQLAlchemy Database Repository & Audit Logger for Module 08.

Persists devices, execution plans, actions, protocol commands, attempts,
verifications, locks, failures, and audit records.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy import String, Float, Boolean, Text, Integer, DateTime, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import structlog

from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    pass


class ExecutionPlanRecord(Base):
    """DB table: execution_plans"""
    __tablename__ = "execution_plans"

    execution_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), index=True)
    station_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(32), index=True)
    actions_count: Mapped[int] = mapped_column(Integer, default=0)
    full_payload_json: Mapped[str] = mapped_column(Text)


class AuditLogRecord(Base):
    """DB table: audit_logs"""
    __tablename__ = "audit_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(String(64), index=True)
    plan_id: Mapped[str] = mapped_column(String(64), index=True)
    station_id: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64), default="execution_engine")
    details_json: Mapped[str] = mapped_column(Text)


_engine = None
_async_session_factory = None


def init_engine(settings: Settings):
    global _engine, _async_session_factory
    if _engine is None:
        _engine = create_async_engine(settings.database_url, echo=False)
        _async_session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


async def create_tables():
    if _engine is not None:
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def dispose_engine():
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_db_session():
    if _async_session_factory is None:
        init_engine(Settings())
        await create_tables()
    assert _async_session_factory is not None
    async with _async_session_factory() as session:
        yield session


class ExecutionRepository:
    """Repository for persisting execution runs and audit logs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_execution(self, execution_result: Dict[str, Any]) -> None:
        record = ExecutionPlanRecord(
            execution_id=execution_result["execution_id"],
            plan_id=execution_result["plan_id"],
            station_id=execution_result.get("station_id", "POLAR-STATION-ALPHA"),
            status=execution_result["status"],
            actions_count=execution_result.get("total_actions", 0),
            full_payload_json=json.dumps(execution_result, default=str),
        )
        self.session.add(record)

        audit = AuditLogRecord(
            execution_id=execution_result["execution_id"],
            plan_id=execution_result["plan_id"],
            station_id=execution_result.get("station_id", "POLAR-STATION-ALPHA"),
            action=f"EXECUTION_{execution_result['status']}",
            details_json=json.dumps(
                {
                    "status": execution_result["status"],
                    "verifications_count": len(execution_result.get("verifications", [])),
                }
            ),
        )
        self.session.add(audit)
        await self.session.commit()

    async def get_execution(self, execution_id: str) -> Optional[Dict[str, Any]]:
        stmt = select(ExecutionPlanRecord).where(ExecutionPlanRecord.execution_id == execution_id)
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
        if record:
            return json.loads(record.full_payload_json)
        return None
