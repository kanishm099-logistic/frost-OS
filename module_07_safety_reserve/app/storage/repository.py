"""
Async SQLAlchemy Database Repository & Audit Logger for Module 07.

Persists safety validations, reserve calculations, constraint violations,
emergency events, and state transitions to SQLite / PostgreSQL / TimescaleDB.
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


class SafetyValidationRecord(Base):
    """DB table: safety_validations"""
    __tablename__ = "safety_validations"

    validation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(64), index=True)
    station_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(32), index=True)
    validation_mode: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(32))
    reserve_status: Mapped[str] = mapped_column(String(32))
    overall_risk_level: Mapped[str] = mapped_column(String(32))
    is_executable: Mapped[bool] = mapped_column(Boolean, default=False)
    required_replan: Mapped[bool] = mapped_column(Boolean, default=False)
    explanation: Mapped[str] = mapped_column(Text)
    full_payload_json: Mapped[str] = mapped_column(Text)


class AuditLogRecord(Base):
    """DB table: audit_logs"""
    __tablename__ = "audit_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    validation_id: Mapped[str] = mapped_column(String(64), index=True)
    plan_id: Mapped[str] = mapped_column(String(64), index=True)
    station_id: Mapped[str] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64), default="safety_engine")
    details_json: Mapped[str] = mapped_column(Text)


_engine = None
_async_session_factory = None


def init_engine(settings: Settings):
    """Initialize async database engine."""
    global _engine, _async_session_factory
    if _engine is None:
        _engine = create_async_engine(settings.database_url, echo=False)
        _async_session_factory = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)


async def create_tables():
    """Create database tables if they do not exist."""
    if _engine is not None:
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


async def dispose_engine():
    """Dispose database engine connections."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_db_session():
    """Dependency injector for async DB sessions."""
    if _async_session_factory is None:
        init_engine(Settings())
        await create_tables()
    assert _async_session_factory is not None
    async with _async_session_factory() as session:
        yield session


class SafetyRepository:
    """Repository for persisting safety validations and audit records."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_validation(self, validation_result: Any) -> None:
        """Persist a ValidationResult to DB."""
        record = SafetyValidationRecord(
            validation_id=validation_result.validation_id,
            plan_id=validation_result.plan_id,
            station_id=validation_result.station_id,
            created_at=validation_result.timestamp,
            status=validation_result.status.value,
            validation_mode=validation_result.validation_mode.value,
            policy_version=validation_result.policy_version,
            reserve_status=validation_result.reserve_status,
            overall_risk_level=validation_result.overall_risk_level.value,
            is_executable=validation_result.is_executable,
            required_replan=validation_result.required_replan,
            explanation=validation_result.explanation,
            full_payload_json=json.dumps(validation_result.model_dump(), default=str),
        )
        self.session.add(record)

        # Audit entry
        audit = AuditLogRecord(
            validation_id=validation_result.validation_id,
            plan_id=validation_result.plan_id,
            station_id=validation_result.station_id,
            action=f"SAFETY_DECISION_{validation_result.status.value}",
            details_json=json.dumps(
                {
                    "status": validation_result.status.value,
                    "policy_version": validation_result.policy_version,
                    "hard_violations_count": len(validation_result.hard_violations),
                    "reserve_margin_kwh": validation_result.reserve_calculation.reserve_margin_kwh,
                }
            ),
        )
        self.session.add(audit)
        await self.session.commit()

    async def get_validation(self, validation_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a validation record by validation_id."""
        stmt = select(SafetyValidationRecord).where(SafetyValidationRecord.validation_id == validation_id)
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
        if record:
            return json.loads(record.full_payload_json)
        return None

    async def get_validation_by_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve latest validation record by plan_id."""
        stmt = (
            select(SafetyValidationRecord)
            .where(SafetyValidationRecord.plan_id == plan_id)
            .order_by(SafetyValidationRecord.created_at.desc())
        )
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
        if record:
            return json.loads(record.full_payload_json)
        return None
