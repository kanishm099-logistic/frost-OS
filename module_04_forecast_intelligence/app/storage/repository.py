"""
Frost OS Module 04 — Storage Repositories.

Provides async CRUD abstractions over forecast runs, time series, weather observations,
risks, scenarios, and model registry.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.forecast import (
    DataQuality,
    ForecastRecord,
    ForecastRun,
    ForecastTarget,
)
from app.models.risk import ForecastRisk, RiskLevel, RiskType
from app.models.scenario import ScenarioResult, ScenarioType
from app.models.weather import WeatherObservation
from app.storage.database import (
    ForecastRecordORM,
    ForecastRiskORM,
    ForecastRunORM,
    ModelRegistryORM,
    ScenarioRecordORM,
    WeatherObservationORM,
)


class ForecastRepository:
    """Async repository for forecast runs and point predictions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_forecast_run(self, run: ForecastRun) -> None:
        """Persist forecast run metadata and all atomic forecast records."""
        run_orm = ForecastRunORM(
            run_id=run.run_id,
            station_id=run.station_id,
            created_at=run.created_at,
            horizon_hours=run.horizon_hours,
            record_count=len(run.records),
            data_quality=run.metadata.get("data_quality", "GOOD"),
            metadata_json=run.metadata,
        )
        self.session.add(run_orm)

        for rec in run.records:
            rec_orm = ForecastRecordORM(
                forecast_id=rec.forecast_id,
                run_id=run.run_id,
                station_id=rec.station_id,
                created_at=rec.created_at,
                horizon_minutes=rec.horizon_minutes,
                target=rec.target.value if hasattr(rec.target, "value") else str(rec.target),
                timestamp=rec.timestamp,
                prediction=rec.prediction,
                lower_bound=rec.lower_bound,
                upper_bound=rec.upper_bound,
                confidence=rec.confidence,
                unit=rec.unit,
                model_version=rec.model_version,
                data_quality=rec.data_quality.value if hasattr(rec.data_quality, "value") else str(rec.data_quality),
            )
            self.session.add(rec_orm)
        await self.session.flush()

    async def list_runs(self, station_id: str, limit: int = 10) -> list[ForecastRunORM]:
        """List past forecast runs."""
        stmt = (
            select(ForecastRunORM)
            .where(ForecastRunORM.station_id == station_id)
            .order_by(desc(ForecastRunORM.created_at))
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

    async def get_run(self, run_id: str) -> tuple[ForecastRunORM | None, list[ForecastRecord]]:
        """Retrieve run metadata and all associated atomic records."""
        stmt_run = select(ForecastRunORM).where(ForecastRunORM.run_id == run_id)
        res_run = await self.session.execute(stmt_run)
        run_orm = res_run.scalar_one_or_none()
        if not run_orm:
            return None, []

        stmt_recs = (
            select(ForecastRecordORM)
            .where(ForecastRecordORM.run_id == run_id)
            .order_by(ForecastRecordORM.timestamp)
        )
        res_recs = await self.session.execute(stmt_recs)
        orm_recs = res_recs.scalars().all()

        records = [
            ForecastRecord(
                forecast_id=r.forecast_id,
                station_id=r.station_id,
                created_at=r.created_at,
                horizon_minutes=r.horizon_minutes,
                target=ForecastTarget(r.target),
                timestamp=r.timestamp,
                prediction=r.prediction,
                lower_bound=r.lower_bound,
                upper_bound=r.upper_bound,
                confidence=r.confidence,
                unit=r.unit,
                model_version=r.model_version,
                data_quality=DataQuality(r.data_quality),
            )
            for r in orm_recs
        ]
        return run_orm, records

    async def get_latest_forecasts_by_target(
        self,
        station_id: str,
        targets: list[ForecastTarget],
    ) -> list[ForecastRecord]:
        """Fetch records from the most recent forecast run for specific targets."""
        stmt_latest_run = (
            select(ForecastRunORM.run_id)
            .where(ForecastRunORM.station_id == station_id)
            .order_by(desc(ForecastRunORM.created_at))
            .limit(1)
        )
        res_run = await self.session.execute(stmt_latest_run)
        run_id = res_run.scalar_one_or_none()
        if not run_id:
            return []

        target_vals = [t.value for t in targets]
        stmt = (
            select(ForecastRecordORM)
            .where(
                ForecastRecordORM.run_id == run_id,
                ForecastRecordORM.target.in_(target_vals),
            )
            .order_by(ForecastRecordORM.timestamp)
        )
        res = await self.session.execute(stmt)
        return [
            ForecastRecord(
                forecast_id=r.forecast_id,
                station_id=r.station_id,
                created_at=r.created_at,
                horizon_minutes=r.horizon_minutes,
                target=ForecastTarget(r.target),
                timestamp=r.timestamp,
                prediction=r.prediction,
                lower_bound=r.lower_bound,
                upper_bound=r.upper_bound,
                confidence=r.confidence,
                unit=r.unit,
                model_version=r.model_version,
                data_quality=DataQuality(r.data_quality),
            )
            for r in res.scalars().all()
        ]


class WeatherRepository:
    """Async repository for weather observations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_observation(self, obs: WeatherObservation) -> None:
        orm = WeatherObservationORM(
            station_id=obs.station_id,
            timestamp=obs.timestamp,
            temperature_c=obs.temperature_c,
            pressure_hpa=obs.pressure_hpa,
            wind_speed_ms=obs.wind_speed_ms,
            wind_direction_deg=obs.wind_direction_deg,
            cloud_cover_pct=obs.cloud_cover_pct,
            solar_radiation_wm2=obs.global_horizontal_irradiance_wm2,
            relative_humidity_pct=obs.relative_humidity_pct,
            condition=obs.condition.value if hasattr(obs.condition, "value") else str(obs.condition),
            source=obs.source,
        )
        self.session.add(orm)
        await self.session.flush()

    async def get_recent_observations(
        self, station_id: str, hours: int = 72
    ) -> list[WeatherObservationORM]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        stmt = (
            select(WeatherObservationORM)
            .where(
                WeatherObservationORM.station_id == station_id,
                WeatherObservationORM.timestamp >= cutoff,
            )
            .order_by(WeatherObservationORM.timestamp)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


class RiskRepository:
    """Async repository for forecast risks."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_risks(self, risks: list[ForecastRisk]) -> None:
        for r in risks:
            orm = ForecastRiskORM(
                risk_id=r.risk_id,
                station_id=r.station_id,
                timestamp=r.timestamp,
                risk_type=r.risk_type.value if hasattr(r.risk_type, "value") else str(r.risk_type),
                risk_level=r.risk_level.value if hasattr(r.risk_level, "value") else str(r.risk_level),
                probability=r.probability,
                lead_time_minutes=r.lead_time_minutes,
                target_time=r.target_time,
                impact_description=r.impact_description,
                recommended_advisory=r.recommended_advisory,
                details_json=r.details,
            )
            self.session.add(orm)
        await self.session.flush()

    async def get_active_risks(self, station_id: str) -> list[ForecastRiskORM]:
        stmt = (
            select(ForecastRiskORM)
            .where(ForecastRiskORM.station_id == station_id)
            .order_by(desc(ForecastRiskORM.timestamp))
            .limit(20)
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())


class ScenarioRepository:
    """Async repository for what-if scenarios."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_scenario(self, scen: ScenarioResult) -> None:
        orm = ScenarioRecordORM(
            scenario_id=scen.scenario_id,
            station_id=scen.station_id,
            scenario_type=scen.scenario_type.value if hasattr(scen.scenario_type, "value") else str(scen.scenario_type),
            created_at=scen.created_at,
            description=scen.description,
            projected_shortage_kwh=scen.projected_shortage_kwh,
            worst_case_deficit_kw=scen.worst_case_deficit_kw,
            min_battery_soc_pct=scen.min_battery_soc_pct,
            min_hydrogen_level_pct=scen.min_hydrogen_level_pct,
            metadata_json=scen.metadata,
        )
        self.session.add(orm)
        await self.session.flush()

    async def get_scenario(self, scenario_id: str) -> ScenarioRecordORM | None:
        stmt = select(ScenarioRecordORM).where(ScenarioRecordORM.scenario_id == scenario_id)
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()


class ModelRepository:
    """Async repository for model registry."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_models(self) -> list[ModelRegistryORM]:
        stmt = select(ModelRegistryORM).order_by(ModelRegistryORM.model_name)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
