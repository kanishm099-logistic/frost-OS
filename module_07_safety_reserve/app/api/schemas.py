"""
Module 07 REST API Request & Response Schemas.
"""

from __future__ import annotations

from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

from app.models.safety_decision import ValidationMode, SafetyDecisionStatus
from app.models.validation import ValidationResult
from app.models.reserve import ReserveCalculation
from app.models.risk import RiskAssessmentItem


class SafetyValidateHTTPRequest(BaseModel):
    """HTTP Request payload for plan validation."""
    proposed_plan: Dict[str, Any]
    energy_state: Optional[Dict[str, Any]] = None
    missions: Optional[List[Dict[str, Any]]] = None
    forecast: Optional[Dict[str, Any]] = None
    equipment_health: Optional[Dict[str, Any]] = None
    validation_mode: ValidationMode = ValidationMode.NORMAL
    weather_event: str = "NORMAL"


class SafetyValidateHTTPResponse(BaseModel):
    """HTTP Response for plan validation."""
    success: bool
    status: SafetyDecisionStatus
    validation_id: str
    plan_id: str
    is_executable: bool
    result: ValidationResult
    agent_explanation: Dict[str, Any]


class SimulationHTTPRequest(BaseModel):
    """HTTP Request for scenario simulation."""
    station_id: str = "POLAR-STATION-ALPHA"
    scenario_name: str = "NORMAL"  # "NORMAL", "LOW_RENEWABLE", "STORM", "EMERGENCY"
    custom_plan: Optional[Dict[str, Any]] = None


class SystemStatusHTTPResponse(BaseModel):
    """Subsystem status response."""
    service: str = "Module 07 Safety + Reserve Intelligence"
    status: str = "HEALTHY"
    station_id: str
    policy_version: str
    deterministic_mode: bool = True
    llm_safety_decisions: bool = False  # Always False per core safety principle
    redis_connected: bool = True
    database_connected: bool = True
