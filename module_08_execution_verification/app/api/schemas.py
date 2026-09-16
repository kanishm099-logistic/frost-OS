"""
Module 08 REST API Schemas.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

from app.models.execution import ActionPlanModel


class ExecutePlanHTTPRequest(BaseModel):
    """HTTP Request to execute an authorized ActionPlan."""
    plan: ActionPlanModel
    idempotency_key: Optional[str] = None


class ExecutePlanHTTPResponse(BaseModel):
    """HTTP Response for plan execution."""
    success: bool
    status: str
    execution_id: str
    plan_id: str
    reason: Optional[str] = None
    verifications: List[Dict[str, Any]] = Field(default_factory=list)


class SystemStatusHTTPResponse(BaseModel):
    """System operational status response."""
    service: str = "Module 08 Execution + Verification Intelligence"
    status: str = "HEALTHY"
    station_id: str
    registered_devices_count: int
    active_locks_count: int = 0
