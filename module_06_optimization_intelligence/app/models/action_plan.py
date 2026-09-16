"""
Action Plan Models.

Represents high-level operational action proposals for Module 01 (Orchestrator).
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """High-level operational action types emitted by Module 06."""
    START_MISSION = "START_MISSION"
    PAUSE_MISSION = "PAUSE_MISSION"
    DEFER_MISSION = "DEFER_MISSION"
    SET_MISSION_POWER = "SET_MISSION_POWER"
    CHARGE_BATTERY = "CHARGE_BATTERY"
    DISCHARGE_BATTERY = "DISCHARGE_BATTERY"
    USE_HYDROGEN = "USE_HYDROGEN"
    HOLD_HYDROGEN = "HOLD_HYDROGEN"
    CURTAIL_RENEWABLE = "CURTAIL_RENEWABLE"
    SHIFT_LOAD = "SHIFT_LOAD"


class ActionItem(BaseModel):
    """Specific operational action step within an ActionPlan."""
    action_id: str
    action_type: ActionType
    target_entity_id: str
    time_step: int
    start_time_minutes: int
    power_kw: float = 0.0
    energy_kwh: float = 0.0
    priority: str = "P2"
    rationale: str = ""
    parameters: Dict[str, Any] = Field(default_factory=dict)


class ActionPlan(BaseModel):
    """Complete ActionPlan proposal for Module 01 Orchestration."""
    plan_id: str
    optimization_id: str
    station_id: str
    created_at: str
    horizon_minutes: int
    time_step_minutes: int
    status: str = "PROPOSED"  # PROPOSED, APPROVED, REJECTED
    is_executable: bool = True
    actions: List[ActionItem] = Field(default_factory=list)
    summary: str = ""
