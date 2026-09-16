"""
Frost OS Module 02 — Mission Agent Tests.

Tests the agentic interpretation, missing field identification,
and explanation generation capabilities.
"""

from __future__ import annotations

from app.agents.mission_agent import MissionAgent
from app.models.mission import Flexibility, MissionType
from app.models.priority import PriorityLevel


class TestMissionAgent:
    """Test agentic reasoning and interpretation layer."""

    def test_interpret_incomplete_request(self, mission_agent):
        """Agent should classify text, identify missing fields, and suggest safe envelopes."""
        interpretation = mission_agent.interpret_request(
            name="Deep Core Drill",
            description="Ice core extraction and cryogenic spectrometer analysis",
            raw_data={},  # completely missing power and duration
        )

        assert interpretation.inferred_type == MissionType.RESEARCH
        assert interpretation.suggested_priority == PriorityLevel.P1
        assert "required_power_kw" in interpretation.missing_fields
        assert "expected_duration_minutes" in interpretation.missing_fields
        assert "deadline" in interpretation.missing_fields
        assert interpretation.suggested_power_envelope["min_power_kw"] > 0
        assert interpretation.suggested_power_envelope["required_power_kw"] > 0

    def test_explain_mission_profile(self, mission_agent, mission_engine, sample_p1_mission):
        """Agent should generate structured, human-readable explanations of profiles."""
        profile = mission_engine.create_profile(sample_p1_mission)
        explanation = mission_agent.explain_mission_profile(profile)

        assert explanation["mission_id"] == sample_p1_mission.mission_id
        assert explanation["priority"] == "P1"
        assert explanation["is_protected"] is True
        assert explanation["energy_summary"]["buffer_percentage"] == "+30.0%"
        assert "agent_rationale" in explanation
        assert "144.0 kWh" in explanation["agent_rationale"]
