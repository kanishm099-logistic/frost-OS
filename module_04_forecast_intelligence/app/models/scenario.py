"""
Frost OS Module 04 — Operational Scenario Domain Models.

Defines the 9 standard operational what-if scenarios for Module 06 Optimization
and Module 07 Reserve/Safety.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.models.forecast import ForecastRecord


class ScenarioType(str, enum.Enum):
    """Supported 9 operational scenarios."""
    BASELINE = "BASELINE"
    LOW_RENEWABLE = "LOW_RENEWABLE"
    HIGH_RENEWABLE = "HIGH_RENEWABLE"
    HIGH_LOAD = "HIGH_LOAD"
    LOW_WIND = "LOW_WIND"
    SOLAR_DROP = "SOLAR_DROP"
    STORM = "STORM"
    EQUIPMENT_DEGRADATION = "EQUIPMENT_DEGRADATION"
    COMMUNICATION_LOSS = "COMMUNICATION_LOSS"


class ScenarioConfig(BaseModel):
    """Configuration parameters overriding base inputs for scenario evaluation."""
    scenario_type: ScenarioType
    wind_multiplier: float = Field(default=1.0, ge=0.0, le=3.0)
    solar_multiplier: float = Field(default=1.0, ge=0.0, le=3.0)
    load_multiplier: float = Field(default=1.0, ge=0.1, le=3.0)
    cloud_cover_override: float | None = Field(default=None, ge=0.0, le=100.0)
    temperature_delta_c: float = Field(default=0.0, description="Temperature shift relative to base NWP")
    wind_speed_override_ms: float | None = Field(default=None, ge=0.0)
    equipment_derating_factor: float = Field(default=1.0, ge=0.0, le=1.0)
    uncertainty_multiplier: float = Field(default=1.0, ge=0.5, le=5.0)
    description: str = Field(default="")


class ScenarioResult(BaseModel):
    """Output of a scenario simulation run."""
    scenario_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    station_id: str
    scenario_type: ScenarioType
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    description: str
    records: list[ForecastRecord] = Field(default_factory=list)
    projected_shortage_kwh: float = Field(default=0.0, ge=0.0)
    worst_case_deficit_kw: float = Field(default=0.0, ge=0.0)
    min_battery_soc_pct: float = Field(default=100.0, ge=0.0, le=100.0)
    min_hydrogen_level_pct: float = Field(default=100.0, ge=0.0, le=100.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
