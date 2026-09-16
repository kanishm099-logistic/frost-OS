"""
Frost OS Module 05 — Equipment Domain & ORM Models.

Defines typed equipment registry, operating limits, and equipment status
for all polar station infrastructure assets.
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
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import JSON

# Universal JSON type (JSONB on PostgreSQL, JSON on SQLite)
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


# ── SQLAlchemy Base ───────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Declarative base for Module 05 ORM models."""
    pass


# ── Enumerations ──────────────────────────────────────────────────────

class EquipmentType(str, enum.Enum):
    """Categories of polar station equipment assets."""
    WIND_TURBINE = "WIND_TURBINE"
    SOLAR_ARRAY = "SOLAR_ARRAY"
    BATTERY = "BATTERY"
    HYDROGEN_TANK = "HYDROGEN_TANK"
    ELECTROLYZER = "ELECTROLYZER"
    FUEL_CELL = "FUEL_CELL"
    INVERTER = "INVERTER"
    CONVERTER = "CONVERTER"
    PUMP = "PUMP"
    SENSOR = "SENSOR"
    THERMAL_SYSTEM = "THERMAL_SYSTEM"
    CUSTOM = "CUSTOM"


class EquipmentStatus(str, enum.Enum):
    """Operational status of an equipment asset."""
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    MAINTENANCE = "MAINTENANCE"
    UNKNOWN = "UNKNOWN"


# ── Pydantic Domain Models ───────────────────────────────────────────

class OperatingLimits(BaseModel):
    """Safe operating boundaries for an equipment asset."""
    min_temperature_c: float | None = Field(default=None, description="Minimum operating temperature °C")
    max_temperature_c: float | None = Field(default=None, description="Maximum operating temperature °C")
    min_voltage_v: float | None = Field(default=None, description="Minimum operating voltage")
    max_voltage_v: float | None = Field(default=None, description="Maximum operating voltage")
    min_current_a: float | None = Field(default=None, description="Minimum current draw")
    max_current_a: float | None = Field(default=None, description="Maximum current draw")
    max_power_kw: float | None = Field(default=None, description="Maximum power output/draw")
    max_vibration: float | None = Field(default=None, description="Maximum safe vibration level")
    max_pressure_bar: float | None = Field(default=None, description="Maximum safe pressure")
    min_pressure_bar: float | None = Field(default=None, description="Minimum safe pressure")
    max_rpm: float | None = Field(default=None, description="Maximum safe RPM")
    min_rpm: float | None = Field(default=None, description="Minimum safe RPM")


class Equipment(BaseModel):
    """Typed equipment asset definition with operational metadata."""
    equipment_id: str = Field(
        ..., min_length=1, max_length=100,
        description="Unique equipment identifier",
    )
    station_id: str = Field(
        ..., min_length=1, max_length=100,
        description="Station where equipment is installed",
    )
    type: EquipmentType = Field(..., description="Equipment category")
    manufacturer: str = Field(default="Unknown", max_length=200)
    model: str = Field(default="Unknown", max_length=200)
    capacity: float | None = Field(default=None, ge=0.0, description="Nominal capacity (kWh or other)")
    rated_power_kw: float | None = Field(default=None, ge=0.0, description="Nameplate power rating")
    operating_limits: OperatingLimits = Field(default_factory=OperatingLimits)
    location: str = Field(default="", max_length=200, description="Physical location description")
    status: EquipmentStatus = Field(default=EquipmentStatus.ONLINE)
    installation_date: datetime | None = Field(default=None)
    last_service_at: datetime | None = Field(default=None)
    health_score: float = Field(default=100.0, ge=0.0, le=100.0)
    state_of_health: float = Field(default=100.0, ge=0.0, le=100.0, description="SOH percentage")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("installation_date", "last_service_at", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class OperatingBaseline(BaseModel):
    """Normal operating profile for an equipment asset under specific conditions."""
    baseline_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    equipment_id: str
    equipment_type: EquipmentType
    condition_bins: dict[str, Any] = Field(
        default_factory=dict,
        description="Operating condition ranges this baseline covers",
    )
    expected_values: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Metric → {mean, std, min, max, count} under these conditions",
    )
    sample_count: int = Field(default=0, ge=0)
    valid_from: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_to: datetime | None = Field(default=None)
    model_version: str = Field(default="v0.1.0")


# ── SQLAlchemy ORM Models ─────────────────────────────────────────────

class EquipmentRecord(Base):
    """Persistent equipment registry."""

    __tablename__ = "equipment"

    equipment_id = Column(String(100), primary_key=True)
    station_id = Column(String(100), nullable=False, index=True)
    equipment_type = Column(
        SQLEnum(EquipmentType, name="equipment_type_enum"),
        nullable=False, index=True,
    )
    manufacturer = Column(String(200), nullable=False, default="Unknown")
    model = Column(String(200), nullable=False, default="Unknown")
    capacity = Column(Float, nullable=True)
    rated_power_kw = Column(Float, nullable=True)
    operating_limits_json = Column(JSON_TYPE, nullable=False, default={})
    location = Column(String(200), nullable=False, default="")
    status = Column(
        SQLEnum(EquipmentStatus, name="equipment_status_enum"),
        nullable=False, default="ONLINE",
    )
    installation_date = Column(DateTime(timezone=True), nullable=True)
    last_service_at = Column(DateTime(timezone=True), nullable=True)
    health_score = Column(Float, nullable=False, default=100.0)
    state_of_health = Column(Float, nullable=False, default=100.0)
    metadata_json = Column(JSON_TYPE, nullable=False, default={})
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class EquipmentBaselineRecord(Base):
    """Persistent equipment operating baseline."""

    __tablename__ = "equipment_baselines"

    baseline_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    equipment_id = Column(String(100), nullable=False, index=True)
    equipment_type = Column(
        SQLEnum(EquipmentType, name="equipment_type_enum", create_type=False),
        nullable=False,
    )
    condition_bins_json = Column(JSON_TYPE, nullable=False, default={})
    expected_values_json = Column(JSON_TYPE, nullable=False, default={})
    sample_count = Column(Float, nullable=False, default=0)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_to = Column(DateTime(timezone=True), nullable=True)
    model_version = Column(String(50), nullable=False, default="v0.1.0")

    __table_args__ = (
        Index("ix_baseline_equipment", "equipment_id", "valid_from"),
    )


class EquipmentOperatingLimitsRecord(Base):
    """Per-equipment operating limits registry."""

    __tablename__ = "equipment_operating_limits"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    equipment_id = Column(String(100), nullable=False, unique=True, index=True)
    limits_json = Column(JSON_TYPE, nullable=False, default={})
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class MaintenanceRecord(Base):
    """Equipment maintenance history for health scoring."""

    __tablename__ = "maintenance_records"

    record_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    equipment_id = Column(String(100), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    maintenance_type = Column(String(100), nullable=False)
    description = Column(String(1000), nullable=True)
    performed_by = Column(String(200), nullable=True)
    metadata_json = Column(JSON_TYPE, nullable=False, default={})


class ModelRegistryRecord(Base):
    """ML model version registry and metadata."""

    __tablename__ = "model_registry"

    model_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_name = Column(String(200), nullable=False, index=True)
    model_version = Column(String(50), nullable=False)
    equipment_type = Column(String(50), nullable=True)
    training_start = Column(DateTime(timezone=True), nullable=True)
    training_end = Column(DateTime(timezone=True), nullable=True)
    features_json = Column(JSON_TYPE, nullable=False, default=[])
    metrics_json = Column(JSON_TYPE, nullable=False, default={})
    model_path = Column(String(500), nullable=True)
    is_active = Column(String(10), nullable=False, default="true")
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    validated = Column(String(10), nullable=False, default="false")

    __table_args__ = (
        Index("ix_model_registry_name_version", "model_name", "model_version"),
    )


class ModelMetricsRecord(Base):
    """ML model performance metrics."""

    __tablename__ = "model_metrics"

    metric_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    model_id = Column(String(36), nullable=False, index=True)
    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Float, nullable=False)
    evaluated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    metadata_json = Column(JSON_TYPE, nullable=False, default={})


class AuditLogRecord(Base):
    """Audit trail for diagnostic operations and model changes."""

    __tablename__ = "audit_logs"

    log_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True,
                       default=lambda: datetime.now(timezone.utc))
    action = Column(String(100), nullable=False, index=True)
    actor = Column(String(200), nullable=False, default="system")
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String(100), nullable=True)
    details_json = Column(JSON_TYPE, nullable=False, default={})

    __table_args__ = (
        Index("ix_audit_logs_action_ts", "action", "timestamp"),
    )
