"""
Frost OS Module 05 — Diagnostic Result Model.

Complete diagnostic result Pydantic model for API responses
and event payloads. This is the primary output type of Module 05.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.models.anomaly import Anomaly
from app.models.fault import FaultHypothesis
from app.models.health import DataQuality, HealthState
from app.models.risk import FailureRisk


class DiagnosticResultModel(BaseModel):
    """
    Pydantic model for the complete diagnostic result.

    Used for serialization in API responses and event payloads.
    Module 05 produces this as its primary output.
    All recommendations are informational only — M05 does NOT control hardware.
    """
    diagnostic_id: str
    equipment_id: str
    station_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    health_score: float = Field(default=100.0, ge=0.0, le=100.0)
    health_state: HealthState = Field(default=HealthState.HEALTHY)
    anomaly_detected: bool = Field(default=False)
    anomalies: list[Anomaly] = Field(default_factory=list)
    fault_hypotheses: list[FaultHypothesis] = Field(default_factory=list)
    failure_risk: FailureRisk | None = Field(default=None)
    degradation: dict[str, Any] = Field(default_factory=dict)
    data_quality: DataQuality = Field(default=DataQuality.GOOD)
    recommended_investigation: list[str] = Field(default_factory=list)
    model_version: str = Field(default="v0.1.0")
