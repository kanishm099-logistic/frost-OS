"""
Frost OS Module 04 — Risk & Energy Shortage Domain Models.

Defines probabilistic risk types, risk severity levels, and shortage forecast metrics.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RiskLevel(str, enum.Enum):
    """Categorical risk severity."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskType(str, enum.Enum):
    """Forecast-based operational risk categories."""
    LOW_RENEWABLE_RISK = "LOW_RENEWABLE_RISK"
    ENERGY_DEFICIT_RISK = "ENERGY_DEFICIT_RISK"
    BATTERY_LOW_RISK = "BATTERY_LOW_RISK"
    HYDROGEN_DEPLETION_RISK = "HYDROGEN_DEPLETION_RISK"
    HIGH_LOAD_RISK = "HIGH_LOAD_RISK"
    WIND_COLLAPSE_RISK = "WIND_COLLAPSE_RISK"
    SOLAR_DROP_RISK = "SOLAR_DROP_RISK"


class ForecastRisk(BaseModel):
    """Individual forecast-driven operational risk entry."""
    risk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    station_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    risk_type: RiskType
    risk_level: RiskLevel
    probability: float = Field(..., ge=0.0, le=1.0, description="Statistically justified probability")
    lead_time_minutes: int = Field(..., ge=0, description="Lead time until risk event")
    target_time: datetime = Field(..., description="Timestamp of anticipated peak risk")
    impact_description: str
    recommended_advisory: str = Field(
        default="", description="Advisory note for M01/M06/M07 (no control dispatch)"
    )
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", "target_time", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class EnergyShortageAssessment(BaseModel):
    """
    Structured Advisory Energy Shortage Assessment for M06 Optimizer and M07 Reserve/Safety:
    - expected_shortage_kwh
    - worst_case_shortage_kwh
    - shortage_probability
    - first_risk_time
    - risk_duration_minutes
    """
    station_id: str
    evaluation_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    horizon_hours: int = 72
    has_shortage_risk: bool = False
    expected_shortage_kwh: float = Field(default=0.0, ge=0.0)
    worst_case_shortage_kwh: float = Field(default=0.0, ge=0.0)
    shortage_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    first_risk_time: datetime | None = None
    risk_duration_minutes: int = Field(default=0, ge=0)
    peak_deficit_kw: float = Field(default=0.0, ge=0.0)
    primary_driver: str = Field(default="NONE")
    active_risks: list[ForecastRisk] = Field(default_factory=list)

    @field_validator("evaluation_time", "first_risk_time", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v
