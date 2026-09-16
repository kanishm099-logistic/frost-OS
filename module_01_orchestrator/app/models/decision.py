"""
Frost OS Module 01 — Decision Domain Models.

Implements the decision state machine with enforced transitions,
decision context aggregation, and audit-trail persistence.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Index, String, Text

from app.models.event import Base, JSON_TYPE, Severity


# ── Decision State Machine ────────────────────────────────────────────

class DecisionStatus(str, enum.Enum):
    """Decision lifecycle states."""
    DETECTED = "DETECTED"
    ANALYZING = "ANALYZING"
    PREDICTED = "PREDICTED"
    OPTIMIZING = "OPTIMIZING"
    VALIDATING = "VALIDATING"
    AWAITING_AUTHORIZATION = "AWAITING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    # Failure states
    REJECTED = "REJECTED"
    REOPTIMIZING = "REOPTIMIZING"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    CANCELLED = "CANCELLED"


# Valid state transitions — enforced at runtime
VALID_TRANSITIONS: dict[DecisionStatus, list[DecisionStatus]] = {
    DecisionStatus.DETECTED: [DecisionStatus.ANALYZING, DecisionStatus.CANCELLED],
    DecisionStatus.ANALYZING: [DecisionStatus.PREDICTED, DecisionStatus.EXECUTION_FAILED, DecisionStatus.CANCELLED],
    DecisionStatus.PREDICTED: [DecisionStatus.OPTIMIZING, DecisionStatus.REOPTIMIZING, DecisionStatus.CANCELLED],
    DecisionStatus.OPTIMIZING: [DecisionStatus.VALIDATING, DecisionStatus.REOPTIMIZING, DecisionStatus.CANCELLED],
    DecisionStatus.VALIDATING: [
        DecisionStatus.AWAITING_AUTHORIZATION,
        DecisionStatus.AUTHORIZED,  # Emergency bypass (M07 emergency flag)
        DecisionStatus.CANCELLED,
    ],
    DecisionStatus.AWAITING_AUTHORIZATION: [DecisionStatus.AUTHORIZED, DecisionStatus.REJECTED],
    DecisionStatus.AUTHORIZED: [DecisionStatus.EXECUTING],
    DecisionStatus.EXECUTING: [DecisionStatus.VERIFYING, DecisionStatus.EXECUTION_FAILED],
    DecisionStatus.VERIFYING: [DecisionStatus.COMPLETED, DecisionStatus.EXECUTION_FAILED],
    DecisionStatus.REOPTIMIZING: [DecisionStatus.OPTIMIZING, DecisionStatus.CANCELLED],
    DecisionStatus.EXECUTION_FAILED: [DecisionStatus.REOPTIMIZING, DecisionStatus.CANCELLED],
    DecisionStatus.REJECTED: [],  # Terminal
    DecisionStatus.COMPLETED: [],  # Terminal
    DecisionStatus.CANCELLED: [],  # Terminal
}


def validate_transition(current: DecisionStatus, target: DecisionStatus) -> bool:
    """Check if a state transition is valid according to the state machine."""
    allowed = VALID_TRANSITIONS.get(current, [])
    return target in allowed


# ── Module Response Models ────────────────────────────────────────────

class ModuleResponse(BaseModel):
    """Response from a specialist module."""
    module_name: str
    status: str = "success"  # success | error | degraded | timeout
    data: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    error_message: str | None = None
    is_degraded: bool = False


# ── Decision Context ──────────────────────────────────────────────────

class DecisionContext(BaseModel):
    """
    Aggregated context from all specialist modules for a decision.

    This is the central data structure passed through the workflow pipeline.
    """
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: str
    station_id: str
    correlation_id: str
    event_type: str
    severity: Severity
    workflow_name: str

    # Module responses (populated as pipeline progresses)
    energy_analysis: ModuleResponse | None = None
    forecast_analysis: ModuleResponse | None = None
    diagnostic_analysis: ModuleResponse | None = None
    mission_analysis: ModuleResponse | None = None
    optimization_result: ModuleResponse | None = None
    reserve_validation: ModuleResponse | None = None
    safety_validation: ModuleResponse | None = None

    # Aggregated insights
    is_emergency: bool = False
    degraded_modules: list[str] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Decision Pydantic Model ──────────────────────────────────────────

class Decision(BaseModel):
    """Tracks a decision through its lifecycle."""
    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_id: str
    station_id: str
    correlation_id: str
    status: DecisionStatus = DecisionStatus.DETECTED
    workflow_name: str
    context: DecisionContext | None = None
    action_plan_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── SQLAlchemy ORM Models ─────────────────────────────────────────────

class DecisionRecord(Base):
    """Persistent storage for decisions."""

    __tablename__ = "decisions"

    decision_id = Column(String(36), primary_key=True)
    event_id = Column(String(36), ForeignKey("events.event_id"), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    correlation_id = Column(String(36), nullable=False, index=True)
    status = Column(Enum(DecisionStatus, name="decision_status_enum"), nullable=False)
    workflow_name = Column(String(100), nullable=False)
    context_data = Column(JSON_TYPE, nullable=True)
    action_plan_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_decisions_station_status", "station_id", "status"),
    )


class DecisionTransitionRecord(Base):
    """Audit log of every decision state transition."""

    __tablename__ = "decision_transitions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    decision_id = Column(String(36), ForeignKey("decisions.decision_id"), nullable=False, index=True)
    from_status = Column(Enum(DecisionStatus, name="decision_status_enum", create_type=False), nullable=False)
    to_status = Column(Enum(DecisionStatus, name="decision_status_enum", create_type=False), nullable=False)
    reason = Column(Text, nullable=True)
    actor = Column(String(255), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_transitions_decision_ts", "decision_id", "timestamp"),
    )
