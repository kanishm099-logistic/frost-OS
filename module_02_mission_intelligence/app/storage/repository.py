"""
Frost OS Module 02 — Repository Layer.

Async repositories for missions, state transitions, and audit logs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.mission import (
    AuditLogRecord,
    Mission,
    MissionRecord,
    MissionState,
    MissionStateTransitionRecord,
)

logger = structlog.get_logger(__name__)


class MissionRepository:
    """Data access repository for station missions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, mission: Mission) -> MissionRecord:
        """Persist a new mission."""
        record = MissionRecord.from_domain(mission)
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_id(self, mission_id: str) -> MissionRecord | None:
        """Retrieve a mission record by ID."""
        stmt = select(MissionRecord).where(MissionRecord.mission_id == mission_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_domain_by_id(self, mission_id: str) -> Mission | None:
        """Retrieve a mission domain model by ID."""
        record = await self.get_by_id(mission_id)
        return record.to_domain() if record else None

    async def list_all(
        self,
        station_id: str | None = None,
        status: MissionState | None = None,
    ) -> list[MissionRecord]:
        """List mission records matching criteria."""
        stmt = select(MissionRecord)
        if station_id:
            stmt = stmt.where(MissionRecord.station_id == station_id)
        if status:
            stmt = stmt.where(MissionRecord.status == status)

        stmt = stmt.order_by(MissionRecord.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all_domain(
        self,
        station_id: str | None = None,
        status: MissionState | None = None,
    ) -> list[Mission]:
        """List mission domain models matching criteria."""
        records = await self.list_all(station_id, status)
        return [r.to_domain() for r in records]

    async def update(self, mission: Mission) -> MissionRecord:
        """Update an existing mission record."""
        mission.updated_at = datetime.now(timezone.utc)
        stmt = (
            update(MissionRecord)
            .where(MissionRecord.mission_id == mission.mission_id)
            .values(
                name=mission.name,
                description=mission.description,
                type=mission.type,
                priority=mission.priority,
                required_power_kw=mission.required_power_kw,
                min_power_kw=mission.min_power_kw,
                max_power_kw=mission.max_power_kw,
                expected_duration_minutes=mission.expected_duration_minutes,
                deadline=mission.deadline,
                flexibility=mission.flexibility,
                energy_required_kwh=mission.energy_required_kwh,
                buffer_kwh=mission.buffer_kwh,
                protected_energy_kwh=mission.protected_energy_kwh,
                status=mission.status,
                dependencies_json=mission.dependencies,
                earliest_start=mission.earliest_start,
                latest_start=mission.latest_start,
                updated_at=mission.updated_at,
                metadata_json=mission.metadata,
            )
        )
        await self._session.execute(stmt)
        await self._session.flush()

        updated = await self.get_by_id(mission.mission_id)
        if not updated:
            raise ValueError(f"Mission {mission.mission_id} not found after update")
        return updated

    async def delete(self, mission_id: str) -> bool:
        """Delete a mission record by ID."""
        stmt = delete(MissionRecord).where(MissionRecord.mission_id == mission_id)
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def record_transition(
        self,
        mission_id: str,
        from_state: MissionState,
        to_state: MissionState,
        reason: str | None = None,
        actor: str | None = None,
    ) -> MissionStateTransitionRecord:
        """Record an immutable state transition in the audit log."""
        record = MissionStateTransitionRecord(
            id=str(uuid.uuid4()),
            mission_id=mission_id,
            from_state=from_state,
            to_state=to_state,
            reason=reason or "",
            actor=actor or "system",
            timestamp=datetime.now(timezone.utc),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_transitions(self, mission_id: str) -> list[MissionStateTransitionRecord]:
        """Retrieve chronological history of state transitions for a mission."""
        stmt = (
            select(MissionStateTransitionRecord)
            .where(MissionStateTransitionRecord.mission_id == mission_id)
            .order_by(MissionStateTransitionRecord.timestamp.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class AuditRepository:
    """Repository for appending and querying audit trail entries."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        station_id: str,
        actor: str,
        action: str,
        correlation_id: str,
        mission_id: str | None = None,
        details: dict[str, Any] | None = None,
        status: str = "success",
    ) -> AuditLogRecord:
        """Record an operation in the audit log."""
        record = AuditLogRecord(
            id=str(uuid.uuid4()),
            station_id=station_id,
            actor=actor,
            action=action,
            correlation_id=correlation_id,
            mission_id=mission_id,
            details=details or {},
            status=status,
            timestamp=datetime.now(timezone.utc),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def list_logs(self, station_id: str, limit: int = 50) -> list[AuditLogRecord]:
        """List recent audit logs for a station."""
        stmt = (
            select(AuditLogRecord)
            .where(AuditLogRecord.station_id == station_id)
            .order_by(AuditLogRecord.timestamp.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
