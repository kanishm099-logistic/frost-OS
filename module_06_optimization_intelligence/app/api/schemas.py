"""
API OpenAPI Schemas.

Request and response schemas for REST endpoints.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

from app.models.optimization_request import OptimizationRequest, ScenarioType
from app.models.optimization_result import OptimizationResult


class RunOptimizationHTTPResponse(BaseModel):
    """HTTP Response for optimization execution."""
    success: bool
    optimization_id: str
    status: str
    result: OptimizationResult
    explanation: str


class ReplanHTTPRequest(BaseModel):
    """HTTP Request triggering rapid re-optimization on state change events."""
    trigger_event: str  # e.g., "GENERATION_DROP", "EQUIPMENT_FAILURE", "RESERVE_REDUCTION"
    station_id: str = "POLAR-STATION-ALPHA"
    correlation_id: Optional[str] = None
    override_request: Optional[OptimizationRequest] = None


class ScenarioRunHTTPResponse(BaseModel):
    """HTTP Response for multi-scenario optimization analysis."""
    station_id: str
    scenarios_evaluated: List[str]
    results: Dict[str, OptimizationResult]
    summary_explanation: str


class ValidationHTTPRequest(BaseModel):
    """HTTP Request for independent validation of candidate variable arrays."""
    request: OptimizationRequest
    var_values: Dict[str, Any]


class ValidationHTTPResponse(BaseModel):
    """HTTP Response for independent validation checks."""
    is_valid: bool
    violation_count: int
    violations: List[Dict[str, Any]]
