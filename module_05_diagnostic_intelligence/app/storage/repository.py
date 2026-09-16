"""
Frost OS Module 05 — Diagnostic Repository.

Async CRUD operations for diagnostic data persistence using
SQLAlchemy sessions and the ORM models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anomaly import AnomalyRecord, Anomaly
from app.models.health import HealthStateRecord, EquipmentHealth
from app.models.fault import FaultRecord, FaultReport
from app.models.risk import FailureRiskRecord, FailureRisk, DegradationTrendRecord
from app.models.equipment import (
    EquipmentRecord, EquipmentBaselineRecord,
    MaintenanceRecord, AuditLogRecord,
    ModelRegistryRecord,
)
from app.storage.database import get_session

logger = structlog.get_logger(__name__)


class DiagnosticRepository:
    """Async repository for diagnostic data persistence."""

    # ── Anomalies ─────────────────────────────────────────────────────

    async def save_anomaly(self, anomaly: Anomaly) -> None:
        """Persist an anomaly detection record."""
        async with get_session() as session:
            record = AnomalyRecord.from_domain(anomaly)
            session.add(record)

    async def get_anomalies_by_equipment(
        self, equipment_id: str, limit: int = 50,
    ) -> list[Anomaly]:
        """Retrieve anomalies for an equipment, most recent first."""
        async with get_session() as session:
            stmt = (
                select(AnomalyRecord)
                .where(AnomalyRecord.equipment_id == equipment_id)
                .order_by(desc(AnomalyRecord.timestamp))
                .limit(limit)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [r.to_domain() for r in records]

    async def get_active_anomalies(
        self, station_id: str,
    ) -> list[Anomaly]:
        """Retrieve all active anomalies for a station."""
        async with get_session() as session:
            stmt = (
                select(AnomalyRecord)
                .where(
                    AnomalyRecord.station_id == station_id,
                    AnomalyRecord.status == "ACTIVE",
                )
                .order_by(desc(AnomalyRecord.timestamp))
                .limit(100)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [r.to_domain() for r in records]

    # ── Health States ─────────────────────────────────────────────────

    async def save_health_state(self, health: EquipmentHealth) -> None:
        """Persist a health state assessment."""
        async with get_session() as session:
            record = HealthStateRecord.from_domain(health)
            session.add(record)

    async def get_health_history(
        self, equipment_id: str, limit: int = 50,
    ) -> list[EquipmentHealth]:
        """Retrieve health assessment history."""
        async with get_session() as session:
            stmt = (
                select(HealthStateRecord)
                .where(HealthStateRecord.equipment_id == equipment_id)
                .order_by(desc(HealthStateRecord.timestamp))
                .limit(limit)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [r.to_domain() for r in records]

    # ── Fault Reports ─────────────────────────────────────────────────

    async def save_fault(self, report: FaultReport) -> None:
        """Persist a fault classification report."""
        async with get_session() as session:
            record = FaultRecord.from_domain(report)
            session.add(record)

    async def get_faults_by_equipment(
        self, equipment_id: str, limit: int = 20,
    ) -> list[FaultReport]:
        """Retrieve fault reports for an equipment."""
        async with get_session() as session:
            stmt = (
                select(FaultRecord)
                .where(FaultRecord.equipment_id == equipment_id)
                .order_by(desc(FaultRecord.timestamp))
                .limit(limit)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [r.to_domain() for r in records]

    # ── Failure Risk ──────────────────────────────────────────────────

    async def save_risk(self, risk: FailureRisk) -> None:
        """Persist a failure risk estimate."""
        async with get_session() as session:
            record = FailureRiskRecord.from_domain(risk)
            session.add(record)

    async def get_risk_by_equipment(
        self, equipment_id: str, limit: int = 20,
    ) -> list[FailureRisk]:
        """Retrieve risk estimation history."""
        async with get_session() as session:
            stmt = (
                select(FailureRiskRecord)
                .where(FailureRiskRecord.equipment_id == equipment_id)
                .order_by(desc(FailureRiskRecord.timestamp))
                .limit(limit)
            )
            result = await session.execute(stmt)
            records = result.scalars().all()
            return [r.to_domain() for r in records]

    # ── Audit Logging ─────────────────────────────────────────────────

    async def log_audit(
        self,
        action: str,
        resource_type: str = "",
        resource_id: str = "",
        actor: str = "system",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Write an audit log entry."""
        async with get_session() as session:
            record = AuditLogRecord(
                action=action,
                actor=actor,
                resource_type=resource_type,
                resource_id=resource_id,
                details_json=details or {},
            )
            session.add(record)
