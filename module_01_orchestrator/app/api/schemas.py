"""
Frost OS Module 01 — API Request/Response Schemas.

Pydantic v2 schemas for API boundary control. Separate from
domain models to allow independent evolution of API contracts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.event import EventType, Severity
from app.models.decision import DecisionStatus
from app.models.action_plan import PlanStatus, SafetyStatus


# ── Event Schemas ─────────────────────────────────────────────────────

class EventCreateRequest(BaseModel):
    """Request schema for creating a new event."""
    source: str = Field(..., min_length=1, max_length=255, description="Event source identifier")
    event_type: EventType = Field(..., description="Event type")
    severity: Severity = Field(default=Severity.MEDIUM, description="Event severity")
    station_id: str = Field(..., min_length=1, max_length=100, description="Station ID")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event payload data")
    correlation_id: str | None = Field(default=None, description="Optional correlation ID")


class EventResponse(BaseModel):
    """Response schema for an event."""
    event_id: str
    timestamp: datetime
    source: str
    event_type: str
    severity: str
    station_id: str
    payload: dict[str, Any]
    correlation_id: str


# ── Decision Schemas ──────────────────────────────────────────────────

class DecisionResponse(BaseModel):
    """Response schema for a decision."""
    decision_id: str
    event_id: str
    station_id: str
    correlation_id: str
    status: str
    workflow_name: str
    action_plan_id: str | None = None
    created_at: datetime
    updated_at: datetime
    transitions: list[TransitionResponse] | None = None


class TransitionResponse(BaseModel):
    """Response schema for a decision transition."""
    from_status: str
    to_status: str
    reason: str | None = None
    actor: str | None = None
    timestamp: datetime


# Fix forward reference
DecisionResponse.model_rebuild()


# ── Action Plan Schemas ───────────────────────────────────────────────

class PlannedActionResponse(BaseModel):
    """Response schema for a planned action."""
    action_id: str
    action_type: str
    target: str
    description: str
    parameters: dict[str, Any]
    priority: int
    estimated_impact_kwh: float
    reversible: bool


class ActionPlanResponse(BaseModel):
    """Response schema for an action plan."""
    plan_id: str
    trigger_event_id: str
    decision_id: str
    station_id: str
    status: str
    reason: str
    actions: list[PlannedActionResponse] = Field(default_factory=list)
    projected_reserve_kwh: float
    required_reserve_kwh: float
    safety_status: str
    requires_authorization: bool
    is_emergency: bool
    created_at: datetime
    expires_at: datetime


# ── Authorization Schemas ─────────────────────────────────────────────

class AuthorizationRequest(BaseModel):
    """Request schema for authorizing/rejecting a plan."""
    authorized_by: str = Field(..., min_length=1, description="Identity of the authorizer")
    reason: str = Field(default="", description="Reason for the decision")


# ── Pipeline Response ─────────────────────────────────────────────────

class PipelineResponse(BaseModel):
    """Response from the event processing pipeline."""
    decision_id: str
    plan_id: str | None = None
    status: str
    requires_authorization: bool = False
    error: str | None = None


# ── Status Schemas ────────────────────────────────────────────────────

class SystemStatusResponse(BaseModel):
    """Response for system status endpoint."""
    service: str
    status: str
    station_id: str
    mock_mode: bool
    database: str
    redis: str
    registered_workflows: list[str]
    uptime_seconds: float


class HealthResponse(BaseModel):
    """Response for health check endpoint."""
    status: str
    database: str
    redis: str
    timestamp: datetime


# ── Workflow Schemas ──────────────────────────────────────────────────

class WorkflowRunResponse(BaseModel):
    """Response schema for a workflow run."""
    workflow_run_id: str
    decision_id: str
    workflow_name: str
    station_id: str
    correlation_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    error_message: str | None = None
