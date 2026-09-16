"""
Frost OS Module 04 — API Request & Response Schemas.

Covers standard REST payloads, what-if scenario requests, model training triggers,
and backward-compatible Module 01 contract payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.forecast import DataQuality, ForecastRecord, ForecastRun, ForecastTarget
from app.models.risk import EnergyShortageAssessment, ForecastRisk
from app.models.scenario import ScenarioConfig, ScenarioResult, ScenarioType


class GenerateForecastRequest(BaseModel):
    """Request payload to initiate a new forecast generation run."""
    station_id: str = Field(default="polar-station-alpha", description="Target station identifier")
    horizon_hours: int = Field(default=72, ge=1, le=168, description="Prediction window in hours")
    weather_event: str | None = Field(
        default=None,
        description="Optional simulated weather event: WIND_COLLAPSE, STORM, SOLAR_DROP, POLAR_NIGHT",
    )
    current_energy_state: dict[str, Any] | None = Field(
        default=None, description="Snapshot from Module 03 Energy Intelligence"
    )
    active_missions: list[dict[str, Any]] | None = Field(
        default=None, description="Active missions from Module 02 Mission Intelligence"
    )
    equipment_health: dict[str, Any] | None = Field(
        default=None, description="Diagnostic signals from Module 05"
    )


class GenerateForecastResponse(BaseModel):
    """Response containing generated forecast run, risks, and shortage assessment."""
    success: bool = True
    run_id: str
    station_id: str
    created_at: datetime
    horizon_hours: int
    record_count: int
    shortage_assessment: EnergyShortageAssessment
    risks: list[ForecastRisk]
    agent_explanation: dict[str, Any]


class ScenarioGenerateRequest(BaseModel):
    """Request to evaluate one or more operational scenarios."""
    station_id: str = "polar-station-alpha"
    scenarios: list[ScenarioType] = Field(
        default_factory=lambda: [
            ScenarioType.BASELINE,
            ScenarioType.LOW_RENEWABLE,
            ScenarioType.HIGH_LOAD,
            ScenarioType.STORM,
        ]
    )
    custom_overrides: dict[str, Any] | None = None


class ScenarioBatchResponse(BaseModel):
    """Container for multiple evaluated scenarios."""
    station_id: str
    results: list[ScenarioResult]


class TrainModelRequest(BaseModel):
    """Trigger retraining of a specific forecast model."""
    hours_history: int = Field(default=72, ge=24, le=720)
    validation_split: float = Field(default=0.2, ge=0.05, le=0.4)


class ValidateModelRequest(BaseModel):
    """Trigger validation evaluation for a model."""
    test_split: float = Field(default=0.2, ge=0.05, le=0.4)


class ServiceStatusResponse(BaseModel):
    """Overall status of Module 04 subsystem."""
    app_name: str
    version: str
    status: str
    station_id: str
    models_active: int
    nwp_provider: str
    db_connected: bool
    redis_connected: bool
    latest_forecast_time: datetime | None = None


# ── Module 01 Orchestrator Inter-Module Contract Schemas ─────────────────────

class WindForecastPoint(BaseModel):
    hour: int
    wind_kw: float
    confidence: float


class SolarForecastPoint(BaseModel):
    hour: int
    solar_kw: float
    confidence: float


class M01ForecastResponseData(BaseModel):
    """Data payload expected by Module 01 ForecastClient."""
    station_id: str
    forecast_hours: int
    wind_forecast: list[WindForecastPoint]
    solar_forecast: list[SolarForecastPoint]
    trend: str
    lowest_generation_kw: float
    lowest_generation_hour: int
    recovery_expected_hour: int
    confidence: float


class M01WeatherResponseData(BaseModel):
    """Data payload expected by Module 01 WeatherClient."""
    station_id: str
    temperature_c: float
    wind_speed_ms: float
    wind_direction_deg: int
    precipitation: str
    visibility_km: float
    icing_risk: str
    storm_warning: bool
    forecast_period_hours: int
