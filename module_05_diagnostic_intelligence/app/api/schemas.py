"""
Frost OS Module 05 — API Schemas.

Pydantic v2 request/response models for the REST API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Request Schemas ───────────────────────────────────────────────────

class TelemetryBatchRequest(BaseModel):
    """Telemetry batch submission."""
    equipment_id: str = Field(..., min_length=1, max_length=100)
    station_id: str = Field(default="", max_length=100)
    readings: list[TelemetryReading] = Field(..., min_length=1, max_length=1000)


class TelemetryReading(BaseModel):
    """Single telemetry reading."""
    signal_name: str = Field(..., min_length=1, max_length=100)
    value: float = Field(...)
    timestamp: datetime | None = Field(default=None)
    unit: str = Field(default="")
    quality: str = Field(default="GOOD")


# Rebuild TelemetryBatchRequest after TelemetryReading is defined
TelemetryBatchRequest.model_rebuild()


class EquipmentRegistration(BaseModel):
    """Register a new equipment asset."""
    equipment_id: str = Field(..., min_length=1, max_length=100)
    station_id: str = Field(..., min_length=1, max_length=100)
    equipment_type: str = Field(..., description="EquipmentType enum value")
    manufacturer: str = Field(default="Unknown")
    model: str = Field(default="Unknown")
    rated_power_kw: float | None = Field(default=None)
    capacity: float | None = Field(default=None)
    location: str = Field(default="")
    operating_limits: dict[str, Any] = Field(default_factory=dict)


# ── Response Schemas ──────────────────────────────────────────────────

class DiagnosticResultResponse(BaseModel):
    """Diagnostic analysis result."""
    diagnostic_id: str
    equipment_id: str
    station_id: str
    timestamp: datetime
    health_score: float
    health_state: str
    anomaly_detected: bool
    anomalies: list[AnomalyResponse]
    fault_hypotheses: list[FaultHypothesisResponse]
    failure_risk: dict[str, Any] | None = None
    degradation: dict[str, Any] = Field(default_factory=dict)
    data_quality: str
    recommended_investigation: list[str]
    model_version: str = "v0.1.0"


class AnomalyResponse(BaseModel):
    """Anomaly detail in response."""
    anomaly_id: str
    type: str
    severity: str
    score: float
    confidence: float
    observed_value: float | None = None
    expected_value: float | None = None
    residual: float | None = None
    signals: list[str]
    possible_causes: list[str]
    detection_layer: str


class FaultHypothesisResponse(BaseModel):
    """Fault hypothesis in response."""
    fault: str
    confidence: float
    evidence: list[str]
    description: str
    recommended_investigation: str = ""
    is_confirmed: bool = False


class HealthResponse(BaseModel):
    """Equipment health summary."""
    equipment_id: str
    health_score: float
    health_state: str
    confidence: float
    data_quality: str
    anomaly_count: int
    scoring_breakdown: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


class StationHealthResponse(BaseModel):
    """Station-wide health summary."""
    station_id: str
    total_equipment: int
    healthy: int
    degraded: int
    at_risk: int
    critical: int
    unknown: int
    average_health_score: float
    active_alerts: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: str


class EquipmentCapabilityResponse(BaseModel):
    """Equipment capability for M06 optimization."""
    equipment_id: str
    available_capacity_kw: float | None
    derated_capacity_kw: float | None
    equipment_health: str
    health_score: float | None = None
    operational_limit: float | None
    failure_risk: str


class ServiceHealthResponse(BaseModel):
    """Module 05 service health."""
    service: str
    version: str
    status: str
    environment: str
    station_id: str
    uptime_seconds: float
    equipment_count: int
    mock_mode: bool
