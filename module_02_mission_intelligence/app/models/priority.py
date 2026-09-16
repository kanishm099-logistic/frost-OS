"""
Frost OS Module 02 — Priority Models and Scoring Types.

Defines operational priority levels P0 to P4 and the multi-criteria
scheduling score structure.
"""

from __future__ import annotations

import enum
from pydantic import BaseModel, Field


class PriorityLevel(str, enum.Enum):
    """Operational priority levels."""
    P0 = "P0"  # Life & Safety Critical (Life support, emergency heating, medical)
    P1 = "P1"  # Mission Critical (Primary science experiments, weather radar, station comms)
    P2 = "P2"  # Operationally Important (Routine lab analysis, essential maintenance)
    P3 = "P3"  # Flexible (Heavy compute simulations, background data processing)
    P4 = "P4"  # Deferrable (Recreational quarters, non-essential convenience)

    @property
    def rank(self) -> int:
        """Numeric rank where 0 is highest priority and 4 is lowest."""
        ranks = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
        return ranks[self.value]

    @property
    def is_protected(self) -> bool:
        """P0 and P1 workloads are strictly protected from arbitrary load shedding."""
        return self in (PriorityLevel.P0, PriorityLevel.P1)


class SchedulingScoreBreakdown(BaseModel):
    """Component breakdown of the multi-criteria scheduling score."""
    priority_score: float = Field(..., ge=0.0, le=100.0, description="Score contribution from priority level")
    urgency_score: float = Field(..., ge=0.0, le=100.0, description="Score contribution from duration vs time")
    deadline_score: float = Field(..., ge=0.0, le=100.0, description="Score contribution from deadline proximity")
    mission_value_score: float = Field(..., ge=0.0, le=100.0, description="Score contribution from strategic value")
    flexibility_score: float = Field(..., ge=0.0, le=100.0, description="Score contribution from inflexibility")
    efficiency_score: float = Field(..., ge=0.0, le=100.0, description="Score contribution from energy intensity")


class SchedulingScore(BaseModel):
    """
    Multi-criteria scheduling score (0.0 to 100.0).

    Used by Module 06 as an optimization input to order workloads.
    Higher score indicates higher dispatch urgency.
    """
    total_score: float = Field(..., ge=0.0, le=100.0, description="Composite weighted score")
    breakdown: SchedulingScoreBreakdown
    is_protected_override: bool = Field(
        default=False,
        description="True if P0/P1 hard policy overrides numeric ranking",
    )
    explanation: str = Field(..., description="Human-readable justification for the score")
