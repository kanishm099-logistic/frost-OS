"""
Safety Decision Models and State Machine Enums.
"""

from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SafetyState(str, Enum):
    """Workflow state transitions during safety evaluation."""
    RECEIVED = "RECEIVED"
    VALIDATING = "VALIDATING"
    RESERVE_CALCULATION = "RESERVE_CALCULATION"
    CONSTRAINT_CHECK = "CONSTRAINT_CHECK"
    RISK_EVALUATION = "RISK_EVALUATION"
    DECISION = "DECISION"


class SafetyDecisionStatus(str, Enum):
    """Final deterministic safety decision outcomes."""
    SAFE = "SAFE"
    UNSAFE = "UNSAFE"
    CONDITIONAL = "CONDITIONAL"
    REQUIRES_REPLAN = "REQUIRES_REPLAN"
    EMERGENCY = "EMERGENCY"


class ValidationMode(str, Enum):
    """Validation conservatism modes."""
    NORMAL = "NORMAL"
    CONSERVATIVE = "CONSERVATIVE"
    STORM = "STORM"
    EMERGENCY = "EMERGENCY"


class StateTransition(BaseModel):
    """State transition record for audit trail."""
    from_state: SafetyState
    to_state: SafetyState
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str
    actor: str = "safety_engine"
