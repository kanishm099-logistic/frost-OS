"""
Safety Constraint & Rule Models.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel


class ConstraintSeverity(str, Enum):
    """Hard (blocking/UNSAFE) vs Soft (tolerable/CONDITIONAL) constraint severity."""
    HARD = "HARD"
    SOFT = "SOFT"


class ConstraintCategory(str, Enum):
    """Domains of operating safety constraints."""
    POWER = "POWER"
    ENERGY = "ENERGY"
    STORAGE = "STORAGE"
    MISSION = "MISSION"
    EQUIPMENT = "EQUIPMENT"
    THERMAL = "THERMAL"
    DATA_QUALITY = "DATA_QUALITY"
    RAMP = "RAMP"


class ConstraintViolation(BaseModel):
    """Detailed record of a constraint boundary violation."""
    rule_id: str
    name: str
    category: ConstraintCategory
    severity: ConstraintSeverity
    description: str
    limit_value: float
    actual_value: float
    unit: str
    is_violated: bool = True
    mitigation_guidance: Optional[str] = None
