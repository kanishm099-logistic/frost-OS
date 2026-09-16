"""
Constraint Models.

Defines mathematical constraints and independent validation violation tracking.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class ConstraintType(str, Enum):
    """Categorization of mathematical constraints."""
    POWER_BALANCE = "POWER_BALANCE"
    MISSION_MIN_POWER = "MISSION_MIN_POWER"
    MISSION_MAX_POWER = "MISSION_MAX_POWER"
    MISSION_WINDOW = "MISSION_WINDOW"
    MISSION_DEPENDENCY = "MISSION_DEPENDENCY"
    BATTERY_SOC = "BATTERY_SOC"
    BATTERY_POWER_LIMIT = "BATTERY_POWER_LIMIT"
    HYDROGEN_RESERVE = "HYDROGEN_RESERVE"
    HYDROGEN_POWER_LIMIT = "HYDROGEN_POWER_LIMIT"
    EQUIPMENT_DERATING = "EQUIPMENT_DERATING"
    STATION_RESERVE = "STATION_RESERVE"


class ConstraintSpec(BaseModel):
    """Specification of a constraint created during model building."""
    name: str
    time_step: int
    constraint_type: ConstraintType
    is_hard: bool = True
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None
    description: str = ""


class ConstraintViolation(BaseModel):
    """Detailed record of a constraint violation detected by the independent validator."""
    constraint_name: str
    time_step: int
    constraint_type: ConstraintType
    actual_value: float
    required_min: Optional[float] = None
    required_max: Optional[float] = None
    unit: str = "kW"
    severity: str = "CRITICAL"  # CRITICAL, WARNING
    description: str = ""
    affected_entity: Optional[str] = None  # e.g., mission_id or equipment_id
