"""
Decision Variable Models.

Defines specifications, bounds, and instantiated values for optimization decision variables.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class VariableType(str, Enum):
    """Supported variable mathematical types."""
    CONTINUOUS = "CONTINUOUS"
    BINARY = "BINARY"
    INTEGER = "INTEGER"


class DecisionVariableSpec(BaseModel):
    """Specification for a single decision variable at time step t."""
    name: str
    time_step: int
    var_type: VariableType = VariableType.CONTINUOUS
    lower_bound: float = 0.0
    upper_bound: float = float("inf")
    unit: str = "kW"
    description: str = ""


class DecisionVariableValue(BaseModel):
    """Resolved value for a decision variable after optimization."""
    name: str
    time_step: int
    value: float
    unit: str = "kW"
    var_type: VariableType = VariableType.CONTINUOUS
    metadata: Dict[str, Any] = Field(default_factory=dict)
