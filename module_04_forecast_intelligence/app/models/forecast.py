"""
Frost OS Module 04 — Forecast Domain Models.

Defines target enumerations, horizon specs, prediction intervals, and structured
time-series forecast records.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ForecastTarget(str, enum.Enum):
    """Supported 10 forecast targets."""
    SOLAR_GENERATION_KW = "solar_generation_kw"
    WIND_GENERATION_KW = "wind_generation_kw"
    TOTAL_RENEWABLE_GENERATION_KW = "total_renewable_generation_kw"
    STATION_LOAD_KW = "station_load_kw"
    BATTERY_SOC_PCT = "battery_soc_pct"
    BATTERY_ENERGY_KWH = "battery_energy_kwh"
    HYDROGEN_LEVEL_PCT = "hydrogen_level_pct"
    ENERGY_SURPLUS_DEFICIT_KW = "energy_surplus_deficit_kw"
    ENERGY_SHORTAGE_RISK = "energy_shortage_risk"
    RENEWABLE_AVAILABILITY = "renewable_availability"


class ForecastHorizon(str, enum.Enum):
    """Configurable standard forecast horizons."""
    H5M = "5m"
    H15M = "15m"
    H30M = "30m"
    H1H = "1h"
    H6H = "6h"
    H24H = "24h"
    H48H = "48h"
    H72H = "72h"


class DataQuality(str, enum.Enum):
    """Quality status reflecting input integrity and confidence."""
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    ESTIMATED = "ESTIMATED"
    STALE_INPUT = "STALE_INPUT"
    CRITICAL_GAP = "CRITICAL_GAP"


class PredictionInterval(BaseModel):
    """Probabilistic prediction interval with lower/upper percentiles."""
    lower_bound: float = Field(..., description="10th percentile (P10) estimate")
    prediction: float = Field(..., description="Median / expected (P50) estimate")
    upper_bound: float = Field(..., description="90th percentile (P90) estimate")
    confidence: float = Field(default=0.80, ge=0.0, le=1.0, description="Nominal confidence coverage (e.g. 80%)")


class ForecastRecord(BaseModel):
    """
    Standardized atomic forecast record conforming to user specification:
    {
      forecast_id, station_id, created_at, horizon_minutes, target,
      timestamp, prediction, lower_bound, upper_bound, confidence,
      unit, model_version, data_quality
    }
    """
    model_config = {"protected_namespaces": ()}

    forecast_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the forecast point",
    )
    station_id: str = Field(..., description="Target station identifier")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Forecast creation/issue time (UTC)",
    )
    horizon_minutes: int = Field(..., ge=0, description="Lead time from creation in minutes")
    target: ForecastTarget = Field(..., description="Forecast target variable")
    timestamp: datetime = Field(..., description="Target validity time (UTC)")
    prediction: float = Field(..., description="Expected / point prediction")
    lower_bound: float = Field(..., description="Lower confidence interval bound (P10)")
    upper_bound: float = Field(..., description="Upper confidence interval bound (P90)")
    confidence: float = Field(
        default=0.85, ge=0.0, le=1.0, description="Statistical confidence (0.0 to 1.0)"
    )
    unit: str = Field(default="kW", description="Measurement unit (kW, kWh, %, index)")
    model_version: str = Field(default="v0.1.0", description="Model version tag")
    data_quality: DataQuality = Field(
        default=DataQuality.GOOD, description="Input data quality indicator"
    )

    @field_validator("created_at", "timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class ForecastRun(BaseModel):
    """Container for a multi-target, multi-horizon forecast execution run."""
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    station_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    horizon_hours: int = 72
    records: list[ForecastRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
