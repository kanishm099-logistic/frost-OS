"""
Frost OS Module 03 — Storage Repositories.

Provides async CRUD operations for Telemetry records, EnergyState snapshots,
and Energy Alerts using SQLAlchemy.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.energy_state import (
    EnergyAlertRecord,
    EnergyState,
    EnergyStateRecord,
)
from app.models.telemetry import (
    MetricType,
    QualityStatus,
    TelemetryRecord,
    TelemetryRecordModel,
)

logger = structlog.get_logger(__name__)


class TelemetryRepository:
    """Repository for persisting and querying sensor telemetry data."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, record: TelemetryRecord) -> TelemetryRecordModel:
        """Persist a single telemetry record."""
        model = TelemetryRecordModel.from_domain(record)
        self.session.add(model)
        return model

    async def save_batch(self, records: list[TelemetryRecord]) -> int:
        """Bulk persist telemetry records."""
        if not records:
            return 0
        models = [TelemetryRecordModel.from_domain(r) for r in records]
        self.session.add_all(models)
        return len(models)

    async def get_latest(
        self,
        station_id: str,
        limit: int = 100,
    ) -> list[TelemetryRecord]:
        """Fetch the most recent telemetry records for a station."""
        stmt = (
            select(TelemetryRecordModel)
            .where(TelemetryRecordModel.station_id == station_id)
            .order_by(desc(TelemetryRecordModel.timestamp))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [row.to_domain() for row in result.scalars().all()]

    async def get_device_history(
        self,
        station_id: str,
        device_id: str,
        limit: int = 100,
    ) -> list[TelemetryRecord]:
        """Fetch historical records for a specific device."""
        stmt = (
            select(TelemetryRecordModel)
            .where(
                TelemetryRecordModel.station_id == station_id,
                TelemetryRecordModel.device_id == device_id,
            )
            .order_by(desc(TelemetryRecordModel.timestamp))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [row.to_domain() for row in result.scalars().all()]

    async def get_range(
        self,
        station_id: str,
        start_time: datetime,
        end_time: datetime,
        metric: MetricType | None = None,
        limit: int = 1000,
    ) -> list[TelemetryRecord]:
        """Fetch telemetry within a time window, optionally filtered by metric."""
        stmt = (
            select(TelemetryRecordModel)
            .where(
                TelemetryRecordModel.station_id == station_id,
                TelemetryRecordModel.timestamp >= start_time,
                TelemetryRecordModel.timestamp <= end_time,
            )
        )
        if metric is not None:
            stmt = stmt.where(TelemetryRecordModel.metric == metric)

        stmt = stmt.order_by(TelemetryRecordModel.timestamp.asc()).limit(limit)
        result = await self.session.execute(stmt)
        return [row.to_domain() for row in result.scalars().all()]


class EnergyStateRepository:
    """Repository for persisting and querying EnergyState snapshots."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, state: EnergyState) -> EnergyStateRecord:
        """Persist a computed EnergyState snapshot."""
        model = EnergyStateRecord(
            state_id=state.state_id,
            timestamp=state.timestamp,
            station_id=state.station_id,
            solar_kw=state.generation.solar_kw,
            wind_kw=state.generation.wind_kw,
            total_generation_kw=state.generation.total_generation_kw,
            total_load_kw=state.load.total_load_kw,
            net_power_kw=state.net_power_kw,
            battery_soc_pct=state.battery.soc_pct,
            battery_available_energy_kwh=state.battery.usable_energy_kwh,
            battery_power_kw=state.battery.power_kw,
            hydrogen_level_pct=state.hydrogen.level_pct,
            hydrogen_available_energy_kwh=state.hydrogen.usable_energy_kwh,
            available_dispatchable_power_kw=state.available_dispatchable_power_kw,
            available_stored_energy_kwh=state.available_stored_energy_kwh,
            data_quality=state.data_quality,
            status=state.status,
            alerts_json=state.active_alerts,
            state_json=state.model_dump(mode="json"),
        )
        self.session.add(model)
        return model

    async def get_latest(self, station_id: str) -> EnergyState | None:
        """Fetch the most recent EnergyState for a station."""
        stmt = (
            select(EnergyStateRecord)
            .where(EnergyStateRecord.station_id == station_id)
            .order_by(desc(EnergyStateRecord.timestamp))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()
        if record is None:
            return None
        return EnergyState.model_validate(record.state_json)

    async def get_history(
        self,
        station_id: str,
        limit: int = 50,
    ) -> list[EnergyState]:
        """Fetch recent EnergyState history."""
        stmt = (
            select(EnergyStateRecord)
            .where(EnergyStateRecord.station_id == station_id)
            .order_by(desc(EnergyStateRecord.timestamp))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        records = result.scalars().all()
        return [EnergyState.model_validate(r.state_json) for r in records]


class AlertRepository:
    """Repository for managing operational energy alerts and anomalies."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, alert: dict[str, Any]) -> EnergyAlertRecord:
        """Persist a single operational alert."""
        ts = alert.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif ts is None:
            ts = datetime.now(timezone.utc)

        model = EnergyAlertRecord(
            alert_id=alert.get("alert_id", str(uuid.uuid4())),
            timestamp=ts,
            station_id=alert.get("station_id", "unknown"),
            alert_type=alert.get("alert_type", "UNKNOWN"),
            severity=alert.get("severity", "WARNING"),
            message=alert.get("message", ""),
            acknowledged=alert.get("acknowledged", False),
            details_json=alert.get("details", {}),
        )
        self.session.add(model)
        return model

    async def save_batch(self, alerts: list[dict[str, Any]]) -> list[EnergyAlertRecord]:
        """Persist multiple operational alerts."""
        models = []
        for a in alerts:
            m = await self.save(a)
            models.append(m)
        return models

    async def get_active(self, station_id: str) -> list[dict[str, Any]]:
        """Fetch all unacknowledged alerts for a station."""
        stmt = (
            select(EnergyAlertRecord)
            .where(
                EnergyAlertRecord.station_id == station_id,
                EnergyAlertRecord.acknowledged == False,  # noqa: E712
            )
            .order_by(desc(EnergyAlertRecord.timestamp))
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "alert_id": r.alert_id,
                "timestamp": r.timestamp.isoformat(),
                "station_id": r.station_id,
                "alert_type": r.alert_type,
                "severity": r.severity,
                "message": r.message,
                "acknowledged": r.acknowledged,
                "details": r.details_json,
            }
            for r in rows
        ]

    async def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an operational alert."""
        stmt = (
            update(EnergyAlertRecord)
            .where(EnergyAlertRecord.alert_id == alert_id)
            .values(acknowledged=True)
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0
