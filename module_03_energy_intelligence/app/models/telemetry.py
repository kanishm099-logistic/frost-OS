"""
Frost OS Module 03 — Telemetry Domain and Storage Models.

Defines strongly typed TelemetryRecord, device classifications, supported metrics,
data quality ratings, physical range validators, and SQLAlchemy ORM models.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    Index,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

# Universal JSON type (JSONB on PostgreSQL, JSON/TEXT on SQLite)
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


# ── SQLAlchemy Base ───────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Declarative base for Module 03 ORM models."""
    pass


# ── Enumerations ──────────────────────────────────────────────────────

class DeviceType(str, enum.Enum):
    """Subsystem device types generating energy telemetry."""
    SOLAR = "SOLAR"
    WIND = "WIND"
    BATTERY = "BATTERY"
    HYDROGEN = "HYDROGEN"
    THERMAL_STORAGE = "THERMAL_STORAGE"
    THERMAL = "THERMAL_STORAGE"
    LOAD = "LOAD"
    INVERTER = "INVERTER"
    CONVERTER = "CONVERTER"
    SENSOR = "SENSOR"
    GENERATOR = "GENERATOR"
    GRID = "GRID"


class MetricType(str, enum.Enum):
    """Standardized physical metrics."""
    POWER_KW = "POWER_KW"
    VOLTAGE_V = "VOLTAGE_V"
    CURRENT_A = "CURRENT_A"
    FREQUENCY_HZ = "FREQUENCY_HZ"
    ENERGY_KWH = "ENERGY_KWH"
    STATE_OF_CHARGE_PCT = "STATE_OF_CHARGE_PCT"
    SOC_PCT = "STATE_OF_CHARGE_PCT"
    STATE_OF_HEALTH_PCT = "STATE_OF_HEALTH_PCT"
    SOH_PCT = "STATE_OF_HEALTH_PCT"
    TEMPERATURE_C = "TEMPERATURE_C"
    PRESSURE_BAR = "PRESSURE_BAR"
    HYDROGEN_LEVEL_PCT = "HYDROGEN_LEVEL_PCT"
    FLOW_RATE = "FLOW_RATE"
    FLOW_RATE_KG_H = "FLOW_RATE"
    WIND_SPEED_MS = "WIND_SPEED_MS"
    WIND_SPEED_M_S = "WIND_SPEED_MS"
    SOLAR_IRRADIANCE_WM2 = "SOLAR_IRRADIANCE_WM2"
    IRRADIANCE_W_M2 = "SOLAR_IRRADIANCE_WM2"


class QualityStatus(str, enum.Enum):
    """Telemetry data quality assessment status."""
    GOOD = "GOOD"          # Valid, within range, confirmed physically plausible
    SUSPECT = "SUSPECT"    # Rate of change anomaly or slight sensor disagreement
    BAD = "BAD"            # Range violation or physically impossible value
    BAD_DATA = "BAD"       # Alias for BAD
    MISSING = "MISSING"    # Missing expected metric
    STALE = "STALE"        # Sensor unresponsive past timeout threshold


# Physical plausible limits for polar microgrid telemetry
METRIC_LIMITS: dict[MetricType, tuple[float, float]] = {
    MetricType.POWER_KW: (-50000.0, 50000.0),            # Negative = charging/import, Positive = discharging/export
    MetricType.VOLTAGE_V: (0.0, 100000.0),
    MetricType.CURRENT_A: (-2000.0, 2000.0),
    MetricType.FREQUENCY_HZ: (0.1, 100.0),
    MetricType.ENERGY_KWH: (0.0, 1e9),
    MetricType.STATE_OF_CHARGE_PCT: (0.0, 100.0),
    MetricType.STATE_OF_HEALTH_PCT: (0.0, 100.0),
    MetricType.TEMPERATURE_C: (-100.0, 150.0),           # Polar station down to -100C
    MetricType.PRESSURE_BAR: (0.0, 1000.0),
    MetricType.HYDROGEN_LEVEL_PCT: (0.0, 100.0),
    MetricType.FLOW_RATE: (0.0, 10000.0),
    MetricType.WIND_SPEED_MS: (0.0, 120.0),              # Hurricane winds up to 120 m/s
    MetricType.SOLAR_IRRADIANCE_WM2: (0.0, 1500.0),      # Top-of-atmosphere solar constant is ~1361 W/m2
}


# ── Domain Model ──────────────────────────────────────────────────────

class TelemetryRecord(BaseModel):
    """
    Strongly-typed individual sensor reading.

    Every telemetry data point passing into Module 03 must conform to this model.
    """
    record_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique telemetry reading identifier",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Reading timestamp (UTC)",
    )
    station_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Station identifier",
    )
    device_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Physical sensor or device identifier",
    )
    device_type: DeviceType = Field(
        ...,
        description="Subsystem device category",
    )
    metric: MetricType = Field(
        ...,
        description="Physical property being measured",
    )
    value: float = Field(
        ...,
        description="Numerical measured value",
    )
    unit: str = Field(
        ...,
        min_length=1,
        max_length=30,
        description="Engineering measurement unit",
    )
    quality: QualityStatus = Field(
        default=QualityStatus.GOOD,
        description="Data quality status",
    )
    source: str = Field(
        default="mqtt",
        max_length=50,
        description="Ingestion source (e.g. mqtt, rest, simulator)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible contextual metadata",
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, v: Any) -> Any:
        """Enforce timezone awareness, defaulting naive datetimes to UTC."""
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ── SQLAlchemy ORM Models ─────────────────────────────────────────────

class DeviceRecord(Base):
    """Registry of station hardware devices and sensors."""

    __tablename__ = "devices"

    device_id = Column(String(100), primary_key=True)
    station_id = Column(String(100), nullable=False, index=True)
    device_type = Column(SQLEnum(DeviceType, name="device_type_enum"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    rating_kw = Column(Float, nullable=True)
    capacity_kwh = Column(Float, nullable=True)
    status = Column(String(50), nullable=False, default="ONLINE")
    last_seen = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column(JSON_TYPE, nullable=False, default={})


class TelemetryRecordModel(Base):
    """Persistent storage for high-frequency telemetry records."""

    __tablename__ = "telemetry"

    record_id = Column(String(36), primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    device_id = Column(String(100), nullable=False, index=True)
    device_type = Column(SQLEnum(DeviceType, name="device_type_enum", create_type=False), nullable=False)
    metric = Column(SQLEnum(MetricType, name="metric_type_enum"), nullable=False, index=True)
    value = Column(Float, nullable=False)
    unit = Column(String(30), nullable=False)
    quality = Column(SQLEnum(QualityStatus, name="quality_status_enum"), nullable=False, index=True)
    source = Column(String(50), nullable=False, default="mqtt")
    metadata_json = Column(JSON_TYPE, nullable=False, default={})

    __table_args__ = (
        Index("ix_telemetry_station_ts", "station_id", "timestamp"),
        Index("ix_telemetry_device_metric", "device_id", "metric"),
    )

    def to_domain(self) -> TelemetryRecord:
        """Convert ORM record to domain TelemetryRecord."""
        return TelemetryRecord(
            record_id=self.record_id,
            timestamp=self.timestamp,
            station_id=self.station_id,
            device_id=self.device_id,
            device_type=self.device_type,
            metric=self.metric,
            value=self.value,
            unit=self.unit,
            quality=self.quality,
            source=self.source,
            metadata=self.metadata_json or {},
        )

    @classmethod
    def from_domain(cls, t: TelemetryRecord) -> "TelemetryRecordModel":
        """Instantiate ORM record from domain TelemetryRecord."""
        return cls(
            record_id=t.record_id,
            timestamp=t.timestamp,
            station_id=t.station_id,
            device_id=t.device_id,
            device_type=t.device_type,
            metric=t.metric,
            value=t.value,
            unit=t.unit,
            quality=t.quality,
            source=t.source,
            metadata_json=t.metadata,
        )
