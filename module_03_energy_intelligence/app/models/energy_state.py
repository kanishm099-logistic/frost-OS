"""
Frost OS Module 03 — Energy State Snapshot & Aggregation Models.

Represents the complete real-time thermodynamic and electrical energy state
of a polar research station.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    Index,
    String,
    Text,
)

from app.models.storage import BatteryState, HydrogenState, ThermalStorageState
from app.models.telemetry import Base, JSON_TYPE, QualityStatus


class EnergyStatus(str, enum.Enum):
    """Overall electrical power balance status."""
    SURPLUS = "SURPLUS"        # Generation exceeds load (excess energy available to charge storage)
    DEFICIT = "DEFICIT"        # Load exceeds generation (must discharge storage or shed load)
    BALANCED = "BALANCED"      # Generation matches load within fine tolerance
    CRITICAL = "CRITICAL"      # Severe deficit with storage depleted below minimum reserve


class GenerationBreakdown(BaseModel):
    """Instantaneous electrical power generation breakdown (kW)."""
    solar: float = Field(default=0.0, ge=0.0, description="Solar PV generation in kW")
    wind: float = Field(default=0.0, ge=0.0, description="Wind turbine generation in kW")
    other: float = Field(default=0.0, ge=0.0, description="Generators or auxiliary supply in kW")
    total: float = Field(default=0.0, ge=0.0, description="Total generation in kW")

    @classmethod
    def from_inputs(cls, **kwargs: Any) -> "GenerationBreakdown":
        mapping = {
            "solar_kw": "solar",
            "wind_kw": "wind",
            "total_generation_kw": "total",
            "other_kw": "other",
        }
        converted = {mapping.get(k, k): v for k, v in kwargs.items()}
        # Filter out pct properties if passed
        converted.pop("solar_pct", None)
        converted.pop("wind_pct", None)
        return cls(**converted)

    @computed_field
    @property
    def solar_kw(self) -> float:
        return self.solar

    @computed_field
    @property
    def wind_kw(self) -> float:
        return self.wind

    @computed_field
    @property
    def total_generation_kw(self) -> float:
        return self.total

    @property
    def solar_pct(self) -> float:
        return round((self.solar / self.total * 100.0), 1) if self.total > 0 else 0.0

    @property
    def wind_pct(self) -> float:
        return round((self.wind / self.total * 100.0), 1) if self.total > 0 else 0.0


class LoadBreakdown(BaseModel):
    """Categorized instantaneous electrical demand (kW)."""
    critical: float = Field(default=0.0, ge=0.0, description="Life support and mission-critical load (P0/P1)")
    operational: float = Field(default=0.0, ge=0.0, description="Operational equipment and labs (P2)")
    flexible: float = Field(default=0.0, ge=0.0, description="Flexible batch loads (P3)")
    deferrable: float = Field(default=0.0, ge=0.0, description="Deferrable convenience loads (P4)")
    total: float = Field(default=0.0, ge=0.0, description="Total station load in kW")

    @classmethod
    def from_inputs(cls, **kwargs: Any) -> "LoadBreakdown":
        mapping = {
            "critical_kw": "critical",
            "operational_kw": "operational",
            "flexible_kw": "flexible",
            "deferrable_kw": "deferrable",
            "total_load_kw": "total",
        }
        converted = {mapping.get(k, k): v for k, v in kwargs.items()}
        return cls(**converted)

    @computed_field
    @property
    def critical_kw(self) -> float:
        return self.critical

    @computed_field
    @property
    def operational_kw(self) -> float:
        return self.operational

    @computed_field
    @property
    def flexible_kw(self) -> float:
        return self.flexible

    @computed_field
    @property
    def deferrable_kw(self) -> float:
        return self.deferrable

    @computed_field
    @property
    def total_load_kw(self) -> float:
        return self.total


class EnergyState(BaseModel):
    """
    Complete physical Energy State of a polar station.

    Produced continuously by Module 03 for Module 01 Orchestrator
    and Module 06 Optimizer.
    """
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Snapshot timestamp (UTC)",
    )
    state_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the state snapshot",
    )
    station_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Station identifier",
    )

    # Generation & Demand
    generation_kw: GenerationBreakdown = Field(default_factory=GenerationBreakdown)
    load_kw: float = Field(default=0.0, ge=0.0, description="Total instantaneous load in kW")
    load_breakdown: LoadBreakdown = Field(default_factory=LoadBreakdown)
    net_power_kw: float = Field(
        default=0.0,
        description="Net power balance (+ surplus, - deficit) in kW",
    )

    # Storage Subsystems
    battery: BatteryState = Field(default_factory=BatteryState)
    hydrogen: HydrogenState = Field(default_factory=HydrogenState)
    thermal: ThermalStorageState = Field(default_factory=ThermalStorageState)

    # Grid / Interconnection
    instantaneous_import_kw: float = Field(default=0.0, ge=0.0, description="Grid import power if present")
    instantaneous_export_kw: float = Field(default=0.0, ge=0.0, description="Grid export power if present")

    # Available Power & Energy for Module 06 Optimizer
    available_power_kw: float = Field(
        default=0.0,
        ge=0.0,
        description="Total available instantaneous generation power in kW",
    )
    available_energy_kwh: float = Field(
        default=0.0,
        ge=0.0,
        description="Total usable stored electrical energy in kWh (BESS + H2)",
    )
    available_dispatchable_power_kw: float = Field(
        default=0.0,
        ge=0.0,
        description="Max discharge capacity from storage + controllable generators in kW",
    )
    available_stored_energy_kwh: float = Field(
        default=0.0,
        ge=0.0,
        description="Total stored chemical and electrochemical energy in kWh",
    )
    estimated_time_to_min_soc_hours: float | None = Field(
        default=None,
        ge=0.0,
        description="Hours until BESS reaches minimum reserve under current deficit",
    )

    # Quality & Operational Status
    data_quality: QualityStatus = Field(
        default=QualityStatus.GOOD,
        description="Composite data quality across telemetry sources",
    )
    status: EnergyStatus = Field(
        default=EnergyStatus.BALANCED,
        description="Operational power balance status",
    )
    active_alerts: list[str] = Field(
        default_factory=list,
        description="Active operational energy and anomaly alerts",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible status payload",
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_inputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "generation" in data and "generation_kw" not in data:
                data["generation_kw"] = data.pop("generation")
            if "load" in data and "load_breakdown" not in data:
                val = data.pop("load")
                if isinstance(val, (dict, LoadBreakdown)):
                    data["load_breakdown"] = val
                    if "load_kw" not in data:
                        data["load_kw"] = getattr(val, "total", val.get("total", 0.0) if isinstance(val, dict) else 0.0)
        return data

    @computed_field
    @property
    def generation(self) -> GenerationBreakdown:
        return self.generation_kw

    @computed_field
    @property
    def load(self) -> LoadBreakdown:
        return self.load_breakdown

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ── SQLAlchemy ORM Models ─────────────────────────────────────────────

class EnergyStateRecord(Base):
    """Periodic persisted snapshots of station EnergyState."""

    __tablename__ = "energy_states"

    state_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    solar_kw = Column(Float, nullable=False, default=0.0)
    wind_kw = Column(Float, nullable=False, default=0.0)
    total_generation_kw = Column(Float, nullable=False, default=0.0)
    total_load_kw = Column(Float, nullable=False, default=0.0)
    net_power_kw = Column(Float, nullable=False, default=0.0)
    battery_soc_pct = Column(Float, nullable=False, default=0.0)
    battery_available_energy_kwh = Column(Float, nullable=False, default=0.0)
    battery_power_kw = Column(Float, nullable=False, default=0.0)
    hydrogen_level_pct = Column(Float, nullable=False, default=0.0)
    hydrogen_available_energy_kwh = Column(Float, nullable=False, default=0.0)
    available_dispatchable_power_kw = Column(Float, nullable=False, default=0.0)
    available_stored_energy_kwh = Column(Float, nullable=False, default=0.0)
    data_quality = Column(SQLEnum(QualityStatus, name="quality_status_enum", create_type=False), nullable=False)
    status = Column(SQLEnum(EnergyStatus, name="energy_status_enum"), nullable=False, index=True)
    alerts_json = Column(JSON_TYPE, nullable=False, default=[])
    state_json = Column(JSON_TYPE, nullable=False, default={})

    __table_args__ = (
        Index("ix_energy_states_station_ts", "station_id", "timestamp"),
    )


class EnergyAlertRecord(Base):
    """Persistent record of energy anomalies and threshold triggers."""

    __tablename__ = "energy_alerts"

    alert_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    alert_type = Column(String(100), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default="WARNING")
    message = Column(Text, nullable=False)
    acknowledged = Column(Boolean, nullable=False, default=False)
    details_json = Column(JSON_TYPE, nullable=False, default={})

    __table_args__ = (
        Index("ix_energy_alerts_station_ts", "station_id", "timestamp"),
    )
