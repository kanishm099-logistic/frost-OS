"""
Frost OS Module 04 — Database & TimescaleDB Schema.

Provides async SQLAlchemy ORM mappings for:
- forecast_runs
- forecasts (time-series hypertable target)
- weather_observations
- model_registry
- model_metrics
- training_runs
- forecast_risks
- scenarios
- audit_logs

Works seamlessly on TimescaleDB/PostgreSQL and SQLite (in-memory test).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import StaticPool

from app.config.settings import get_settings

Base = declarative_base()
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class ForecastRunORM(Base):
    """Metadata for full forecast generation runs."""
    __tablename__ = "forecast_runs"

    run_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    station_id = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    horizon_hours = Column(Integer, nullable=False, default=72)
    record_count = Column(Integer, nullable=False, default=0)
    data_quality = Column(String(30), nullable=False, default="GOOD")
    metadata_json = Column(JSON_TYPE, nullable=False, default=dict)


class ForecastRecordORM(Base):
    """Individual time-series forecast predictions and intervals."""
    __tablename__ = "forecasts"

    forecast_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id = Column(String(36), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    horizon_minutes = Column(Integer, nullable=False)
    target = Column(String(50), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    prediction = Column(Float, nullable=False)
    lower_bound = Column(Float, nullable=False)
    upper_bound = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    unit = Column(String(20), nullable=False, default="kW")
    model_version = Column(String(50), nullable=False)
    data_quality = Column(String(30), nullable=False, default="GOOD")

    __table_args__ = (
        Index("ix_forecasts_station_target_ts", "station_id", "target", "timestamp"),
    )


class WeatherObservationORM(Base):
    """Surface meteorological telemetry records."""
    __tablename__ = "weather_observations"

    observation_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    station_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    temperature_c = Column(Float, nullable=False)
    pressure_hpa = Column(Float, nullable=False)
    wind_speed_ms = Column(Float, nullable=False)
    wind_direction_deg = Column(Float, nullable=False, default=0.0)
    cloud_cover_pct = Column(Float, nullable=False, default=0.0)
    solar_radiation_wm2 = Column(Float, nullable=False, default=0.0)
    relative_humidity_pct = Column(Float, nullable=False, default=80.0)
    condition = Column(String(50), nullable=False, default="CLEAR")
    source = Column(String(50), nullable=False, default="sensor")

    __table_args__ = (
        Index("ix_weather_station_ts", "station_id", "timestamp"),
    )


class ModelRegistryORM(Base):
    """Registered ML models, versions, and deployment status."""
    __tablename__ = "model_registry"

    model_name = Column(String(100), primary_key=True)
    target = Column(String(50), nullable=False, index=True)
    version = Column(String(50), nullable=False)
    model_type = Column(String(100), nullable=False)
    training_data_range = Column(String(100), nullable=False)
    features_json = Column(JSON_TYPE, nullable=False, default=list)
    metrics_json = Column(JSON_TYPE, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(30), nullable=False, default="ACTIVE")


class ModelMetricsORM(Base):
    """Historical evaluation metrics and drift tracking."""
    __tablename__ = "model_metrics"

    metric_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_name = Column(String(100), nullable=False, index=True)
    evaluated_at = Column(DateTime(timezone=True), nullable=False, index=True)
    mae = Column(Float, nullable=False)
    rmse = Column(Float, nullable=False)
    mape = Column(Float, nullable=False)
    interval_coverage_pct = Column(Float, nullable=False, default=85.0)
    details_json = Column(JSON_TYPE, nullable=False, default=dict)


class TrainingRunORM(Base):
    """Log of automated or triggered model training cycles."""
    __tablename__ = "training_runs"

    run_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_name = Column(String(100), nullable=False, index=True)
    target = Column(String(50), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(30), nullable=False, default="PENDING")
    sample_count = Column(Integer, nullable=False, default=0)
    metrics_json = Column(JSON_TYPE, nullable=False, default=dict)


class ForecastRiskORM(Base):
    """Forecast-derived risk alerts."""
    __tablename__ = "forecast_risks"

    risk_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    station_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    risk_type = Column(String(50), nullable=False, index=True)
    risk_level = Column(String(20), nullable=False)
    probability = Column(Float, nullable=False)
    lead_time_minutes = Column(Integer, nullable=False)
    target_time = Column(DateTime(timezone=True), nullable=False)
    impact_description = Column(Text, nullable=False)
    recommended_advisory = Column(Text, nullable=False)
    details_json = Column(JSON_TYPE, nullable=False, default=dict)


class ScenarioRecordORM(Base):
    """Stored what-if scenario simulations."""
    __tablename__ = "scenarios"

    scenario_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    station_id = Column(String(100), nullable=False, index=True)
    scenario_type = Column(String(50), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, index=True)
    description = Column(Text, nullable=False)
    projected_shortage_kwh = Column(Float, nullable=False, default=0.0)
    worst_case_deficit_kw = Column(Float, nullable=False, default=0.0)
    min_battery_soc_pct = Column(Float, nullable=False, default=100.0)
    min_hydrogen_level_pct = Column(Float, nullable=False, default=100.0)
    metadata_json = Column(JSON_TYPE, nullable=False, default=dict)


class AuditLogORM(Base):
    """Audit log of forecasting and model lifecycle actions."""
    __tablename__ = "audit_logs"

    log_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    action = Column(String(100), nullable=False)
    actor = Column(String(100), nullable=False, default="system")
    details_json = Column(JSON_TYPE, nullable=False, default=dict)


_engine = None
_sessionmaker = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        engine_kwargs: dict[str, Any] = {"echo": False}
        if "sqlite" in settings.database_url:
            connect_args["check_same_thread"] = False
            engine_kwargs["poolclass"] = StaticPool
            engine_kwargs["connect_args"] = connect_args
        _engine = create_async_engine(settings.database_url, **engine_kwargs)
    return _engine


def get_session_factory():
    global _sessionmaker
    if _sessionmaker is None:
        engine = get_engine()
        _sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    return _sessionmaker


async def init_db(custom_engine=None) -> None:
    """Initialize all tables."""
    eng = custom_engine or get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for yielding an async session."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
