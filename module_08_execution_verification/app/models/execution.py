"""
Execution Models and Action Types.
"""

from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class ExecutionStateEnum(str, Enum):
    """Execution state machine states."""
    RECEIVED = "RECEIVED"
    AUTH_CHECK = "AUTH_CHECK"
    SAFETY_CHECK = "SAFETY_CHECK"
    VALIDATING = "VALIDATING"
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    
    # Terminal Failure States
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    ROLLBACK_REQUIRED = "ROLLBACK_REQUIRED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class ActionTypeEnum(str, Enum):
    """Supported high-level actions."""
    START_MISSION = "START_MISSION"
    PAUSE_MISSION = "PAUSE_MISSION"
    RESUME_MISSION = "RESUME_MISSION"
    DEFER_MISSION = "DEFER_MISSION"
    SET_MISSION_POWER = "SET_MISSION_POWER"
    CHARGE_BATTERY = "CHARGE_BATTERY"
    DISCHARGE_BATTERY = "DISCHARGE_BATTERY"
    USE_HYDROGEN = "USE_HYDROGEN"
    HOLD_HYDROGEN = "HOLD_HYDROGEN"
    CURTAIL_RENEWABLE = "CURTAIL_RENEWABLE"
    RESTORE_LOAD = "RESTORE_LOAD"
    REDUCE_LOAD = "REDUCE_LOAD"


class ActionItemModel(BaseModel):
    """Structured high-level action inside an authorized ActionPlan."""
    action_id: str
    plan_id: str
    station_id: str
    action_type: ActionTypeEnum
    target_id: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    sequence: int = 1
    expected_result: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 15.0
    rollback_action: Optional[Dict[str, Any]] = None
    status: str = "PENDING"


class ActionPlanModel(BaseModel):
    """Authorized Action Plan received from M01/M07."""
    plan_id: str
    station_id: str
    authorization_id: str
    safety_validation_id: str
    status: str = "SAFE"
    actions: List[ActionItemModel] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    expected_results: Dict[str, Any] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)


class ExecutionRecordModel(BaseModel):
    """Execution lifecycle record for audit tracking."""
    execution_id: str
    plan_id: str
    station_id: str
    status: ExecutionStateEnum
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    action_count: int = 0
    actions_completed: int = 0
    failure_reason: Optional[str] = None
