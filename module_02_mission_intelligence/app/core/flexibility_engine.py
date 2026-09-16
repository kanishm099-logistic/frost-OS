"""
Frost OS Module 02 — Flexibility Engine.

Determines operational degrees of freedom for workloads:
whether they can shift, interrupt, curtail power, or align with renewable generation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pydantic import BaseModel, Field

from app.models.mission import Flexibility, Mission


class FlexibilityProfile(BaseModel):
    """Detailed operational flexibility assessment."""
    flexibility: Flexibility
    interruptible: bool = Field(..., description="Can be paused and resumed")
    shiftable: bool = Field(..., description="Can shift start time within scheduling window")
    can_curtail_power: bool = Field(..., description="Can operate below nominal down to min_power_kw")
    curtailment_potential_kw: float = Field(default=0.0, description="Max power reduction possible in kW")
    earliest_start: datetime | None = None
    latest_start: datetime | None = None
    explanation: str


class FlexibilityEngine:
    """Evaluates mission flexibility and scheduling windows."""

    @staticmethod
    def evaluate_flexibility(
        mission: Mission,
        reference_time: datetime | None = None,
    ) -> FlexibilityProfile:
        """Derive concrete scheduling parameters from mission flexibility classification."""
        now = reference_time or datetime.now(timezone.utc)
        flex = mission.flexibility
        duration = timedelta(minutes=mission.expected_duration_minutes)

        # 1. Determine boolean capabilities based on category
        if flex == Flexibility.INFLEXIBLE:
            interruptible = False
            shiftable = False
            can_curtail = False
            explanation = (
                f"Workload '{mission.name}' is INFLEXIBLE: must run continuously at nominal power "
                f"without shifting or interruption."
            )
        elif flex == Flexibility.PARTIALLY_FLEXIBLE:
            interruptible = False
            shiftable = False
            can_curtail = True
            explanation = (
                f"Workload '{mission.name}' is PARTIALLY_FLEXIBLE: cannot interrupt or shift, "
                f"but can curtail power between {mission.min_power_kw} kW and {mission.max_power_kw} kW."
            )
        elif flex == Flexibility.FLEXIBLE:
            interruptible = True
            shiftable = True
            can_curtail = True
            explanation = (
                f"Workload '{mission.name}' is FLEXIBLE: can shift start time, pause/resume, "
                f"and curtail power to {mission.min_power_kw} kW."
            )
        else:  # DEFERRABLE
            interruptible = True
            shiftable = True
            can_curtail = True
            explanation = (
                f"Workload '{mission.name}' is DEFERRABLE: lowest priority load, can be suspended "
                f"or rescheduled whenever station energy is constrained."
            )

        # 2. Calculate Curtailment Potential
        curtailment_kw = 0.0
        if can_curtail and mission.required_power_kw > mission.min_power_kw:
            curtailment_kw = round(mission.required_power_kw - mission.min_power_kw, 2)

        # 3. Calculate latest start time based on hard deadline
        latest_start = None
        earliest_start = mission.earliest_start or now

        if mission.deadline:
            calculated_latest = mission.deadline - duration
            latest_start = mission.latest_start or calculated_latest
            if latest_start < earliest_start:
                # Infeasible or overdue
                latest_start = earliest_start

        return FlexibilityProfile(
            flexibility=flex,
            interruptible=interruptible,
            shiftable=shiftable,
            can_curtail_power=can_curtail,
            curtailment_potential_kw=curtailment_kw,
            earliest_start=earliest_start,
            latest_start=latest_start,
            explanation=explanation,
        )
