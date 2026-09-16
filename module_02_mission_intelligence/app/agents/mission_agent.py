"""
Frost OS Module 02 — Mission Agent.

Agentic interpretation and coordination layer over deterministic mission engines.
Interprets natural-language intent, identifies missing workload metadata,
and provides transparent reasoning for priority and buffer assignments.

STRICT SAFETY BOUNDARY:
The Mission Agent MUST NOT directly control hardware or allocate station power.
"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field
import structlog

from app.core.mission_engine import MissionEngine
from app.models.mission import Flexibility, Mission, MissionType
from app.models.mission_profile import MissionProfile
from app.models.priority import PriorityLevel

logger = structlog.get_logger(__name__)


class MissionInterpretation(BaseModel):
    """Result of agentic interpretation of a mission request."""
    mission_name: str
    inferred_type: MissionType
    suggested_priority: PriorityLevel
    confidence: float
    missing_fields: list[str] = Field(default_factory=list)
    suggested_power_envelope: dict[str, float]
    suggested_flexibility: Flexibility
    explanation: str


class MissionAgent:
    """Agentic coordinator and reasoning provider for mission intelligence."""

    def __init__(self, engine: MissionEngine) -> None:
        self.engine = engine

    def interpret_request(self, name: str, description: str, raw_data: dict[str, Any] | None = None) -> MissionInterpretation:
        """
        Analyze an unstructured or partially-structured mission submission.
        Identifies missing operational metadata and derives default safe values.
        """
        data = raw_data or {}
        combined_text = f"{name} {description}"
        classification = self.engine.classifier.classify(combined_text)

        missing_fields = []
        if "required_power_kw" not in data:
            missing_fields.append("required_power_kw")
        if "expected_duration_minutes" not in data:
            missing_fields.append("expected_duration_minutes")
        if "deadline" not in data:
            missing_fields.append("deadline")

        # Suggest standard default envelopes for the inferred mission type
        default_envelopes = {
            MissionType.LIFE_SUPPORT: {"min": 35.0, "nominal": 45.0, "max": 60.0, "flex": Flexibility.INFLEXIBLE},
            MissionType.HEATING: {"min": 25.0, "nominal": 40.0, "max": 55.0, "flex": Flexibility.INFLEXIBLE},
            MissionType.MEDICAL: {"min": 15.0, "nominal": 20.0, "max": 30.0, "flex": Flexibility.INFLEXIBLE},
            MissionType.WEATHER_MONITORING: {"min": 15.0, "nominal": 20.0, "max": 25.0, "flex": Flexibility.PARTIALLY_FLEXIBLE},
            MissionType.COMMUNICATION: {"min": 15.0, "nominal": 25.0, "max": 35.0, "flex": Flexibility.PARTIALLY_FLEXIBLE},
            MissionType.RESEARCH: {"min": 50.0, "nominal": 100.0, "max": 140.0, "flex": Flexibility.PARTIALLY_FLEXIBLE},
            MissionType.LABORATORY: {"min": 10.0, "nominal": 20.0, "max": 30.0, "flex": Flexibility.FLEXIBLE},
            MissionType.MAINTENANCE: {"min": 15.0, "nominal": 30.0, "max": 45.0, "flex": Flexibility.FLEXIBLE},
            MissionType.COMPUTING: {"min": 40.0, "nominal": 80.0, "max": 120.0, "flex": Flexibility.FLEXIBLE},
            MissionType.OFFICE: {"min": 5.0, "nominal": 10.0, "max": 15.0, "flex": Flexibility.FLEXIBLE},
            MissionType.RECREATION: {"min": 2.0, "nominal": 8.0, "max": 12.0, "flex": Flexibility.DEFERRABLE},
        }

        envelope = default_envelopes.get(
            classification.mission_type,
            {"min": 10.0, "nominal": 25.0, "max": 40.0, "flex": Flexibility.PARTIALLY_FLEXIBLE},
        )

        return MissionInterpretation(
            mission_name=name,
            inferred_type=classification.mission_type,
            suggested_priority=classification.suggested_priority,
            confidence=classification.confidence,
            missing_fields=missing_fields,
            suggested_power_envelope={
                "min_power_kw": float(data.get("min_power_kw", envelope["min"])),
                "required_power_kw": float(data.get("required_power_kw", envelope["nominal"])),
                "max_power_kw": float(data.get("max_power_kw", envelope["max"])),
            },
            suggested_flexibility=envelope["flex"],
            explanation=(
                f"Classified as {classification.mission_type.value} with suggested priority "
                f"{classification.suggested_priority.value} (Confidence: {classification.confidence:.0%}). "
                f"{classification.reasoning}"
            ),
        )

    def explain_mission_profile(self, profile: MissionProfile) -> dict[str, Any]:
        """Provide detailed human-readable explanation of why a profile was constructed as such."""
        p_desc = {
            PriorityLevel.P0: "Life & Safety Critical (highest protection, no load shedding allowed)",
            PriorityLevel.P1: "Mission Critical (core science/operations, protected buffer)",
            PriorityLevel.P2: "Operationally Important (routine analysis, moderate flexibility)",
            PriorityLevel.P3: "Flexible (heavy computing, candidate for load curtailment)",
            PriorityLevel.P4: "Deferrable (convenience, first candidate for temporary suspension)",
        }

        buffer_pct = (
            round((profile.buffer_kwh / profile.energy_required_kwh) * 100.0, 1)
            if profile.energy_required_kwh > 0
            else 0.0
        )

        return {
            "mission_id": profile.mission_id,
            "name": profile.name,
            "priority": profile.priority.value,
            "priority_description": p_desc.get(profile.priority, ""),
            "is_protected": profile.is_protected,
            "scheduling_score": profile.scheduling_score,
            "energy_summary": {
                "base_energy_kwh": profile.energy_required_kwh,
                "buffer_margin_kwh": profile.buffer_kwh,
                "buffer_percentage": f"+{buffer_pct}%",
                "total_protected_kwh": profile.protected_energy_kwh,
            },
            "power_envelope": {
                "minimum_safe_kw": profile.min_power_kw,
                "nominal_operating_kw": profile.required_power_kw,
                "peak_allowable_kw": profile.max_power_kw,
                "curtailment_room_kw": max(0.0, profile.required_power_kw - profile.min_power_kw),
            },
            "flexibility_status": {
                "flexibility": profile.flexibility.value,
                "can_interrupt": profile.interruptible,
                "can_shift": profile.shiftable,
                "latest_start": profile.latest_start.isoformat() if profile.latest_start else None,
            },
            "agent_rationale": (
                f"Workload '{profile.name}' is scheduled at priority {profile.priority.value} with "
                f"a protected energy buffer of {profile.buffer_kwh} kWh (+{buffer_pct}%). "
                f"Minimum operating threshold is fixed at {profile.min_power_kw} kW. "
                f"Scheduling score is {profile.scheduling_score:.1f}."
            ),
        }
