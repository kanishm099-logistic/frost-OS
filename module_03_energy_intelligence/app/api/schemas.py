"""
Frost OS Module 03 — API Schemas.

Pydantic models for REST endpoints and inter-module contract validation.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field

from app.models.energy_state import EnergyState, EnergyStatus
from app.models.telemetry import TelemetryRecord


class TelemetryBatchRequest(BaseModel):
    """Batch ingestion request for multiple sensor telemetry records."""
    records: list[TelemetryRecord] = Field(
        ...,
        min_length=1,
        description="Collection of sensor telemetry readings",
    )


class TelemetryIngestResponse(BaseModel):
    """Response returned upon processing a telemetry batch."""
    processed_count: int
    rejected_count: int = 0
    station_id: str
    energy_state: EnergyState | None = None
    alerts_triggered: list[str] = Field(default_factory=list)


class AgentQueryRequest(BaseModel):
    """Conversational question for the EnergyAgent."""
    station_id: str = Field(..., description="Target station identifier")
    question: str = Field(..., min_length=2, description="Natural language query")


class AgentQueryResponse(BaseModel):
    """Response from the EnergyAgent."""
    station_id: str
    answer: str
    intent: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class LoadEvaluationRequest(BaseModel):
    """Hypothetical load addition impact assessment request."""
    station_id: str = Field(..., description="Target station identifier")
    additional_kw: float = Field(..., gt=0.0, description="Electrical load draw in kW")
    duration_hours: float = Field(default=1.0, gt=0.0, description="Planned load duration in hours")


class LoadEvaluationResponse(BaseModel):
    """Hypothetical load evaluation results."""
    station_id: str
    additional_kw: float
    duration_hours: float
    current_net_power_kw: float
    projected_net_power_kw: float
    usable_battery_kwh: float
    energy_needed_kwh: float
    projected_runway_hours: float | None
    verdict: str
    feasible: bool
    reason: str


class SimulateRequest(BaseModel):
    """Trigger simulator tick with optional anomaly."""
    anomaly: str | None = Field(default=None, description="Optional anomaly key (e.g. generation_drop, load_spike)")


# ── Module 01 Compatibility Schemas ───────────────────────────────────

class M01GenerationSummary(BaseModel):
    wind_kw: float
    solar_kw: float
    hydrogen_fuel_cell_kw: float = 0.0
    total_generation_kw: float


class M01ConsumptionSummary(BaseModel):
    total_demand_kw: float
    deficit_kw: float


class M01StorageSummary(BaseModel):
    battery_kwh: float
    battery_capacity_kwh: float
    battery_soc_pct: float
    hydrogen_kg: float
    hydrogen_capacity_kg: float


class M01EnergyStatusResponse(BaseModel):
    station_id: str
    generation: M01GenerationSummary
    consumption: M01ConsumptionSummary
    storage: M01StorageSummary
    grid_status: str


class M01AnalysisDetails(BaseModel):
    event_type: str
    previous_generation_kw: float
    current_generation_kw: float
    drop_kw: float
    drop_pct: float
    cause_assessment: str
    battery_runway_hours: float
    immediate_risk: bool
    requires_load_adjustment: bool


class M01AnalyzeResponse(BaseModel):
    station_id: str
    analysis: M01AnalysisDetails
