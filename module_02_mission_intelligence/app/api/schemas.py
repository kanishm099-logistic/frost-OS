"""
Frost OS Module 02 — API Schemas.

Pydantic DTOs for request validation and response formatting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.mission import Flexibility, Mission, MissionState, MissionType
from app.models.mission_profile import MissionProfile
from app.models.priority import PriorityLevel, SchedulingScore


# ── Requests ──────────────────────────────────────────────────────────

class MissionCreateRequest(BaseModel):
    """Request payload to create a new station mission."""
    station_id: str = Field(default="FROST-STATION-ALPHA", description="Station identifier")
    name: str = Field(..., min_length=1, max_length=255, description="Mission title")
    description: str = Field(default="", description="Mission description")
    type: MissionType | None = Field(default=None, description="Explicit mission type or None to auto-classify")
    priority: PriorityLevel | None = Field(default=None, description="Explicit priority or None for default")
    required_power_kw: float = Field(..., gt=0.0, description="Nominal power requirement in kW")
    min_power_kw: float | None = Field(default=None, gt=0.0, description="Minimum safe operating power")
    max_power_kw: float | None = Field(default=None, gt=0.0, description="Maximum peak power draw")
    expected_duration_minutes: int = Field(..., gt=0, description="Duration in minutes")
    deadline: datetime | None = Field(default=None, description="Completion deadline (UTC)")
    flexibility: Flexibility = Field(default=Flexibility.PARTIALLY_FLEXIBLE, description="Flexibility mode")
    dependencies: list[str] = Field(default_factory=list, description="IDs of prerequisite missions")
    earliest_start: datetime | None = Field(default=None, description="Earliest start time (UTC)")
    latest_start: datetime | None = Field(default=None, description="Latest start time (UTC)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Custom metadata")

    @model_validator(mode="after")
    def populate_power_bounds(self) -> "MissionCreateRequest":
        """Default min_power_kw and max_power_kw if omitted."""
        if self.min_power_kw is None:
            self.min_power_kw = round(self.required_power_kw * 0.8, 2)
        if self.max_power_kw is None:
            self.max_power_kw = round(self.required_power_kw * 1.2, 2)

        if self.min_power_kw > self.required_power_kw:
            raise ValueError(f"min_power_kw ({self.min_power_kw}) cannot exceed required_power_kw ({self.required_power_kw})")
        if self.required_power_kw > self.max_power_kw:
            raise ValueError(f"required_power_kw ({self.required_power_kw}) cannot exceed max_power_kw ({self.max_power_kw})")
        return self


class MissionUpdateRequest(BaseModel):
    """Payload to partially update an existing mission."""
    name: str | None = None
    description: str | None = None
    type: MissionType | None = None
    priority: PriorityLevel | None = None
    required_power_kw: float | None = Field(default=None, gt=0.0)
    min_power_kw: float | None = Field(default=None, gt=0.0)
    max_power_kw: float | None = Field(default=None, gt=0.0)
    expected_duration_minutes: int | None = Field(default=None, gt=0)
    deadline: datetime | None = None
    flexibility: Flexibility | None = None
    status: MissionState | None = None
    dependencies: list[str] | None = None
    metadata: dict[str, Any] | None = None


class MissionClassifyRequest(BaseModel):
    """Payload to request automated classification of text description."""
    text: str = Field(..., min_length=1, description="Workload description or title")


class MissionStateActionRequest(BaseModel):
    """Payload for advancing mission state."""
    reason: str = Field(default="", description="Reason for state transition")
    actor: str = Field(default="operator", description="Authorizing entity or user")


class ImpactAnalysisRequest(BaseModel):
    """Event payload from Module 01 to assess impact on station missions."""
    event_id: str | None = None
    event_type: str | None = None
    station_id: str
    severity: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


# ── Responses ─────────────────────────────────────────────────────────

class MissionResponse(BaseModel):
    """Full mission representation."""
    mission: Mission


class MissionListResponse(BaseModel):
    """List of missions."""
    total: int
    missions: list[Mission]


class MissionProfileResponse(BaseModel):
    """MissionProfile representation with explanation."""
    profile: MissionProfile
    explanation: dict[str, Any] = Field(default_factory=dict)


class ActiveMissionsResponse(BaseModel):
    """M01 compatible format for active missions."""
    station_id: str
    active_missions: list[dict[str, Any]]
    total_demand_kw: float


class MissionPrioritiesResponse(BaseModel):
    """M01 compatible format for mission priorities."""
    station_id: str
    priority_order: list[str]
    non_reducible_kw: float
    reducible_kw: float
    total_kw: float


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str = "0.1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now())


class SystemStatusResponse(BaseModel):
    """Module operational status response."""
    service: str
    status: str
    station_id: str
    total_missions: int
    active_missions: int
    total_demand_kw: float
    total_protected_energy_kwh: float
    environment: str
