"""
Frost OS Module 02 — Mission Engine.

Core coordinator unifying classification, energy estimation, priority calculation,
flexibility assessment, buffer calculation, dependency verification, and state transitions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.config.settings import Settings
from app.core.buffer_engine import BufferEngine
from app.core.classifier import MissionClassifier
from app.core.energy_estimator import EnergyEstimator
from app.core.flexibility_engine import FlexibilityEngine
from app.core.priority_engine import PriorityEngine
from app.models.mission import (
    Flexibility,
    Mission,
    MissionState,
    validate_mission_transition,
)
from app.models.mission_profile import MissionProfile
from app.models.priority import PriorityLevel

logger = structlog.get_logger(__name__)


class MissionEngine:
    """Central domain service orchestrating mission analysis and lifecycle logic."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.classifier = MissionClassifier()
        self.priority_engine = PriorityEngine(settings)
        self.energy_estimator = EnergyEstimator()
        self.flexibility_engine = FlexibilityEngine()
        self.buffer_engine = BufferEngine(settings)

    def enrich_mission(self, mission: Mission) -> Mission:
        """
        Calculate and populate all derived fields for a mission:
        base energy, buffer energy, protected energy, and scheduling window.
        """
        # Calculate base energy requirement
        base_energy = self.energy_estimator.calculate_base_energy(
            power_kw=mission.required_power_kw,
            duration_minutes=mission.expected_duration_minutes,
        )

        # Calculate buffer & protected energy
        buffer_kwh, protected_kwh = self.buffer_engine.calculate_buffer(
            priority=mission.priority,
            base_energy_kwh=base_energy,
        )

        # Evaluate flexibility & scheduling windows
        flex_profile = self.flexibility_engine.evaluate_flexibility(mission)

        # Update mission with enriched values
        mission.energy_required_kwh = base_energy
        mission.buffer_kwh = buffer_kwh
        mission.protected_energy_kwh = protected_kwh
        if flex_profile.latest_start:
            mission.latest_start = flex_profile.latest_start
        if flex_profile.earliest_start and not mission.earliest_start:
            mission.earliest_start = flex_profile.earliest_start
        mission.updated_at = datetime.now(timezone.utc)

        return mission

    def create_profile(
        self,
        mission: Mission,
        reference_time: datetime | None = None,
    ) -> MissionProfile:
        """
        Generate a fully realized MissionProfile for consumption by Module 06 and Module 01.
        """
        # Ensure mission is enriched
        enriched = self.enrich_mission(mission)

        # Compute multi-criteria scheduling score
        score_result = self.priority_engine.calculate_score(enriched, reference_time)

        # Evaluate flexibility parameters
        flex_profile = self.flexibility_engine.evaluate_flexibility(enriched, reference_time)

        return MissionProfile(
            mission_id=enriched.mission_id,
            name=enriched.name,
            station_id=enriched.station_id,
            priority=enriched.priority,
            type=enriched.type,
            required_power_kw=enriched.required_power_kw,
            min_power_kw=enriched.min_power_kw,
            max_power_kw=enriched.max_power_kw,
            energy_required_kwh=enriched.energy_required_kwh,
            buffer_kwh=enriched.buffer_kwh,
            protected_energy_kwh=enriched.protected_energy_kwh,
            expected_duration_minutes=enriched.expected_duration_minutes,
            deadline=enriched.deadline,
            flexibility=enriched.flexibility,
            interruptible=flex_profile.interruptible,
            shiftable=flex_profile.shiftable,
            earliest_start=flex_profile.earliest_start,
            latest_start=flex_profile.latest_start,
            dependencies=enriched.dependencies,
            status=enriched.status,
            scheduling_score=score_result.total_score,
            is_protected=score_result.is_protected_override or enriched.priority.is_protected,
            metadata={
                "curtailment_potential_kw": flex_profile.curtailment_potential_kw,
                "score_breakdown": score_result.breakdown.model_dump(),
                "score_explanation": score_result.explanation,
                "flexibility_explanation": flex_profile.explanation,
            },
        )

    def check_dependencies(
        self,
        mission: Mission,
        all_missions: dict[str, Mission],
    ) -> tuple[bool, list[str]]:
        """
        Verify if all prerequisite mission dependencies are satisfied.
        A dependency is satisfied only if its status is COMPLETED.
        """
        if not mission.dependencies:
            return True, []

        unmet = []
        for dep_id in mission.dependencies:
            dep_mission = all_missions.get(dep_id)
            if not dep_mission or dep_mission.status != MissionState.COMPLETED:
                unmet.append(dep_id)

        return len(unmet) == 0, unmet

    def validate_transition(
        self,
        mission: Mission,
        target_state: MissionState,
        all_missions: dict[str, Mission] | None = None,
    ) -> tuple[bool, str]:
        """
        Validate whether mission can transition to target state,
        including state machine validity and prerequisite dependency checks.
        """
        if not validate_mission_transition(mission.status, target_state):
            return (
                False,
                f"Invalid transition from {mission.status.value} to {target_state.value}",
            )

        # If attempting to transition to READY or RUNNING, verify dependencies
        if target_state in (MissionState.READY, MissionState.RUNNING) and all_missions is not None:
            satisfied, unmet = self.check_dependencies(mission, all_missions)
            if not satisfied:
                return (
                    False,
                    f"Cannot transition to {target_state.value}: prerequisite dependencies not completed: {unmet}",
                )

        return True, f"Transition from {mission.status.value} to {target_state.value} is valid"

    def assess_generation_impact(
        self,
        active_missions: list[Mission],
        station_id: str,
        current_generation_kw: float,
        baseline_generation_kw: float,
    ) -> dict[str, Any]:
        """
        Provide mission impact assessment when Module 01 reports generation drops.
        """
        total_demand_kw = sum(m.required_power_kw for m in active_missions)
        deficit_kw = max(0.0, total_demand_kw - current_generation_kw)

        # Categorize missions by priority
        p0_missions = [m for m in active_missions if m.priority == PriorityLevel.P0]
        p1_missions = [m for m in active_missions if m.priority == PriorityLevel.P1]
        p2_missions = [m for m in active_missions if m.priority == PriorityLevel.P2]
        p3_missions = [m for m in active_missions if m.priority == PriorityLevel.P3]
        p4_missions = [m for m in active_missions if m.priority == PriorityLevel.P4]

        # Calculate non-reducible critical load (P0 + P1 at minimum operating power)
        p0_power = sum(m.required_power_kw for m in p0_missions)
        p1_min_power = sum(m.min_power_kw for m in p1_missions)
        critical_floor_kw = p0_power + p1_min_power

        # Calculate curtailment potentials
        reducible_p3_p4_kw = sum(
            self.energy_estimator.calculate_curtailment_potential(m)
            + (m.min_power_kw if m.flexibility == Flexibility.DEFERRABLE else 0.0)
            for m in (p3_missions + p4_missions)
        )
        reducible_p2_kw = sum(
            self.energy_estimator.calculate_curtailment_potential(m)
            for m in p2_missions
        )

        recommendations = []
        if deficit_kw > 0:
            if current_generation_kw < critical_floor_kw:
                recommendations.append(
                    f"CRITICAL: Available generation ({current_generation_kw} kW) is below "
                    f"the station life/mission critical floor ({critical_floor_kw} kW). "
                    "Emergency storage discharge or backup generation required."
                )
            if p4_missions:
                recommendations.append("Pause/defer P4 recreation workloads immediately.")
            if p3_missions and deficit_kw > 0:
                recommendations.append("Curtail P3 computing workloads to minimum power or shift window.")
            if deficit_kw > reducible_p3_p4_kw and p2_missions:
                recommendations.append("Curtail P2 laboratory workloads to minimum operating thresholds.")
        else:
            recommendations.append("Generation adequate to cover all active mission workloads.")

        return {
            "station_id": station_id,
            "total_active_missions": len(active_missions),
            "total_demand_kw": round(total_demand_kw, 2),
            "current_generation_kw": round(current_generation_kw, 2),
            "deficit_kw": round(deficit_kw, 2),
            "critical_floor_kw": round(critical_floor_kw, 2),
            "priority_summary": {
                "P0_count": len(p0_missions),
                "P0_kw": round(sum(m.required_power_kw for m in p0_missions), 2),
                "P1_count": len(p1_missions),
                "P1_kw": round(sum(m.required_power_kw for m in p1_missions), 2),
                "P2_count": len(p2_missions),
                "P2_kw": round(sum(m.required_power_kw for m in p2_missions), 2),
                "P3_count": len(p3_missions),
                "P3_kw": round(sum(m.required_power_kw for m in p3_missions), 2),
                "P4_count": len(p4_missions),
                "P4_kw": round(sum(m.required_power_kw for m in p4_missions), 2),
            },
            "recommendations": recommendations,
        }
