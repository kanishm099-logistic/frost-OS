"""
Frost OS Module 02 — Priority & Scheduling Score Engine.

Calculates multi-criteria scheduling scores without replacing explicit priority levels.
Enforces P0/P1 hard protection rules so critical life-support and science workloads
are never dropped by numeric score anomalies.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from app.config.settings import Settings
from app.models.mission import Flexibility, Mission
from app.models.priority import (
    PriorityLevel,
    SchedulingScore,
    SchedulingScoreBreakdown,
)


class PriorityEngine:
    """Calculates scheduling score and enforces priority policy."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def calculate_score(
        self,
        mission: Mission,
        reference_time: datetime | None = None,
    ) -> SchedulingScore:
        """
        Calculate composite scheduling score for a mission.

        score = w_priority * P + w_urgency * U + w_deadline * D +
                w_value * V + w_flexibility * F + w_efficiency * E
        """
        now = reference_time or datetime.now(timezone.utc)

        # 1. Base Priority Score
        priority_map = {
            PriorityLevel.P0: 100.0,
            PriorityLevel.P1: 80.0,
            PriorityLevel.P2: 60.0,
            PriorityLevel.P3: 40.0,
            PriorityLevel.P4: 20.0,
        }
        p_score = priority_map.get(mission.priority, 50.0)

        # 2. Urgency and Deadline Pressure
        duration_hours = mission.expected_duration_minutes / 60.0
        if mission.deadline is None:
            urgency_score = 25.0
            deadline_score = 20.0
        else:
            time_remaining_hours = (mission.deadline - now).total_seconds() / 3600.0

            if time_remaining_hours <= 0:
                # Mission is overdue
                deadline_score = 100.0
                urgency_score = 100.0
            elif time_remaining_hours <= duration_hours:
                # Time remaining is less than execution duration — zero slack
                deadline_score = 98.0
                urgency_score = 95.0
            else:
                slack_hours = time_remaining_hours - duration_hours
                threshold = self.settings.near_deadline_hours

                if slack_hours <= threshold:
                    # Near deadline: escalate rapidly towards 95
                    fraction = max(0.0, min(1.0, slack_hours / threshold))
                    deadline_score = 80.0 + (15.0 * (1.0 - fraction))
                    urgency_score = 75.0 + (20.0 * (1.0 - fraction))
                else:
                    # Ample slack: decay exponentially
                    decay = math.exp(-slack_hours / 24.0)
                    deadline_score = max(10.0, 70.0 * decay)
                    urgency_score = max(15.0, 60.0 * decay)

        # 3. Mission Value Score
        value_map = {
            PriorityLevel.P0: 100.0,
            PriorityLevel.P1: 85.0,
            PriorityLevel.P2: 65.0,
            PriorityLevel.P3: 45.0,
            PriorityLevel.P4: 25.0,
        }
        val_score = value_map.get(mission.priority, 50.0)

        # 4. Flexibility Score (Inflexible loads score highest because they cannot adapt)
        flex_map = {
            Flexibility.INFLEXIBLE: 100.0,
            Flexibility.PARTIALLY_FLEXIBLE: 70.0,
            Flexibility.FLEXIBLE: 40.0,
            Flexibility.DEFERRABLE: 15.0,
        }
        flex_score = flex_map.get(mission.flexibility, 50.0)

        # 5. Efficiency Score (Normalizes load footprint; smaller loads get a slight efficiency boost)
        eff_score = max(20.0, min(100.0, 100.0 - (mission.required_power_kw * 0.25)))

        # Weighted Sum
        raw_score = (
            self.settings.weight_priority * p_score
            + self.settings.weight_urgency * urgency_score
            + self.settings.weight_deadline * deadline_score
            + self.settings.weight_mission_value * val_score
            + self.settings.weight_flexibility * flex_score
            + self.settings.weight_energy_efficiency * eff_score
        )

        breakdown = SchedulingScoreBreakdown(
            priority_score=round(p_score, 2),
            urgency_score=round(urgency_score, 2),
            deadline_score=round(deadline_score, 2),
            mission_value_score=round(val_score, 2),
            flexibility_score=round(flex_score, 2),
            efficiency_score=round(eff_score, 2),
        )

        # Enforce P0/P1 Hard Protection Rules
        is_override = False
        final_score = raw_score
        if mission.priority == PriorityLevel.P0:
            final_score = max(raw_score, 95.0)
            is_override = True
            explanation = (
                f"P0 Life-Critical override applied. Workload '{mission.name}' is strictly protected "
                f"with score {final_score:.1f} (raw={raw_score:.1f})."
            )
        elif mission.priority == PriorityLevel.P1:
            final_score = max(raw_score, 80.0)
            is_override = True
            explanation = (
                f"P1 Mission-Critical protection applied. Workload '{mission.name}' guaranteed priority floor "
                f"with score {final_score:.1f} (raw={raw_score:.1f})."
            )
        else:
            explanation = (
                f"Computed score {final_score:.1f} for {mission.priority.value} workload '{mission.name}' "
                f"(Urgency={urgency_score:.1f}, Deadline={deadline_score:.1f}, Flex={flex_score:.1f})."
            )

        return SchedulingScore(
            total_score=round(final_score, 2),
            breakdown=breakdown,
            is_protected_override=is_override,
            explanation=explanation,
        )
