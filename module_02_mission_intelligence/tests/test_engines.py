"""
Frost OS Module 02 — Engine Tests.

Tests the deterministic engines:
- Classifier
- Priority Engine
- Energy Estimator (including critical min_power_kw enforcement)
- Buffer Engine
- Flexibility Engine
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from app.core.classifier import MissionClassifier
from app.core.energy_estimator import EnergyEstimator
from app.core.flexibility_engine import FlexibilityEngine
from app.core.priority_engine import PriorityEngine
from app.models.mission import Flexibility, Mission, MissionType
from app.models.priority import PriorityLevel


class TestClassifier:
    """Test deterministic rule-based keyword classification."""

    def setup_method(self):
        self.classifier = MissionClassifier()

    def test_life_support_keywords(self):
        result = self.classifier.classify("Cabin air scrub and O2 generation routine")
        assert result.mission_type == MissionType.LIFE_SUPPORT
        assert result.suggested_priority == PriorityLevel.P0
        assert result.confidence >= 0.70

    def test_weather_monitoring_keywords(self):
        result = self.classifier.classify("Blizzard radar sweep and katabatic wind tracking")
        assert result.mission_type == MissionType.WEATHER_MONITORING
        assert result.suggested_priority == PriorityLevel.P1

    def test_research_keywords(self):
        result = self.classifier.classify("Deep ice core spectrometry sample run")
        assert result.mission_type == MissionType.RESEARCH
        assert result.suggested_priority == PriorityLevel.P1

    def test_computing_keywords(self):
        result = self.classifier.classify("Polar climate model ensemble simulation batch")
        assert result.mission_type == MissionType.COMPUTING
        assert result.suggested_priority == PriorityLevel.P3

    def test_recreation_keywords(self):
        result = self.classifier.classify("Crew quarters gym treadmill and media streaming")
        assert result.mission_type == MissionType.RECREATION
        assert result.suggested_priority == PriorityLevel.P4

    def test_unrecognized_text_fallback(self):
        result = self.classifier.classify("Unknown acoustic vibration recording")
        assert result.mission_type == MissionType.RESEARCH
        assert result.suggested_priority == PriorityLevel.P2
        assert result.confidence < 0.50


class TestPriorityEngine:
    """Test multi-criteria scheduling score calculations."""

    def test_priority_hierarchy(self, mission_engine):
        """Higher priority workloads must score higher than lower under identical timing."""
        now = datetime.now(timezone.utc)
        m_p0 = Mission(
            station_id="STN", name="P0", priority=PriorityLevel.P0,
            required_power_kw=50, min_power_kw=40, max_power_kw=60,
            expected_duration_minutes=60, deadline=now + timedelta(hours=10),
            flexibility=Flexibility.INFLEXIBLE,
        )
        m_p4 = Mission(
            station_id="STN", name="P4", priority=PriorityLevel.P4,
            required_power_kw=50, min_power_kw=40, max_power_kw=60,
            expected_duration_minutes=60, deadline=now + timedelta(hours=10),
            flexibility=Flexibility.DEFERRABLE,
        )

        score_p0 = mission_engine.priority_engine.calculate_score(m_p0, now)
        score_p4 = mission_engine.priority_engine.calculate_score(m_p4, now)

        assert score_p0.total_score > score_p4.total_score
        assert score_p0.is_protected_override is True
        assert score_p0.total_score >= 95.0

    def test_overdue_mission_urgency(self, mission_engine, sample_p1_mission):
        """Overdue mission must receive maximum urgency and deadline pressure."""
        past_deadline = datetime.now(timezone.utc) - timedelta(hours=1)
        sample_p1_mission.deadline = past_deadline

        score = mission_engine.priority_engine.calculate_score(sample_p1_mission)
        assert score.breakdown.deadline_score == 100.0
        assert score.breakdown.urgency_score == 100.0

    def test_ample_slack_reduces_deadline_score(self, mission_engine, sample_p3_mission):
        """Missions with far-future deadlines receive lower deadline pressure."""
        far_future = datetime.now(timezone.utc) + timedelta(days=7)
        sample_p3_mission.deadline = far_future

        score = mission_engine.priority_engine.calculate_score(sample_p3_mission)
        assert score.breakdown.deadline_score < 30.0


class TestEnergyEstimator:
    """Test energy usage calculations and minimum power safety enforcement."""

    def test_base_energy_calculation(self):
        """Verify E = P * t in kWh."""
        # 120 kW for 4 hours (240 min) = 480 kWh
        e = EnergyEstimator.calculate_base_energy(120.0, 240)
        assert e == 480.0

        # With 0.5 utilization
        e_half = EnergyEstimator.calculate_base_energy(120.0, 240, utilization_factor=0.5)
        assert e_half == 240.0

    def test_critical_min_power_enforcement(self, sample_p1_mission):
        """
        CRITICAL REQUIREMENT TEST:
        Prove that a mission with min_power_kw=90 cannot be allocated below 90kW
        merely because energy is scarce.
        """
        sample_p1_mission.min_power_kw = 90.0
        sample_p1_mission.required_power_kw = 120.0
        sample_p1_mission.max_power_kw = 150.0

        # Proposed 70 kW allocation MUST BE REJECTED
        valid, msg = EnergyEstimator.validate_power_allocation(sample_p1_mission, proposed_kw=70.0)
        assert valid is False
        assert "SAFETY VIOLATION" in msg
        assert "90.0 kW" in msg

        # Proposed 89.9 kW MUST BE REJECTED
        valid_edge, _ = EnergyEstimator.validate_power_allocation(sample_p1_mission, proposed_kw=89.9)
        assert valid_edge is False

        # Proposed 90.0 kW MUST BE ACCEPTED
        valid_exact, _ = EnergyEstimator.validate_power_allocation(sample_p1_mission, proposed_kw=90.0)
        assert valid_exact is True

        # Proposed 120.0 kW MUST BE ACCEPTED
        valid_nominal, _ = EnergyEstimator.validate_power_allocation(sample_p1_mission, proposed_kw=120.0)
        assert valid_nominal is True

        # Proposed 160.0 kW (above max 150) MUST BE REJECTED
        valid_over, msg_over = EnergyEstimator.validate_power_allocation(sample_p1_mission, proposed_kw=160.0)
        assert valid_over is False
        assert "exceeds maximum" in msg_over

    def test_shutdown_flexibility_rules(self):
        """Inflexible workloads cannot be shutdown to 0 kW, but flexible workloads can."""
        inflexible_mission = Mission(
            station_id="S", name="Life Support", priority=PriorityLevel.P0,
            required_power_kw=45, min_power_kw=35, max_power_kw=60,
            expected_duration_minutes=60, flexibility=Flexibility.INFLEXIBLE,
        )
        valid_inflex, _ = EnergyEstimator.validate_power_allocation(inflexible_mission, proposed_kw=0.0)
        assert valid_inflex is False

        flexible_mission = Mission(
            station_id="S", name="Batch Compute", priority=PriorityLevel.P3,
            required_power_kw=100, min_power_kw=60, max_power_kw=120,
            expected_duration_minutes=60, flexibility=Flexibility.FLEXIBLE,
        )
        valid_flex, _ = EnergyEstimator.validate_power_allocation(flexible_mission, proposed_kw=0.0)
        assert valid_flex is True


class TestBufferEngine:
    """Test buffer calculation and protected energy totals."""

    def test_p0_buffer_factor(self, mission_engine):
        """P0 must receive +50% protective buffer."""
        buffer_kwh, protected = mission_engine.buffer_engine.calculate_buffer(
            PriorityLevel.P0, base_energy_kwh=100.0
        )
        assert buffer_kwh == 50.0
        assert protected == 150.0

    def test_p1_buffer_factor_ice_core(self, mission_engine):
        """P1 Ice Core Analysis (480 kWh) must receive +30% buffer (144 kWh) = 624 kWh."""
        buffer_kwh, protected = mission_engine.buffer_engine.calculate_buffer(
            PriorityLevel.P1, base_energy_kwh=480.0
        )
        assert buffer_kwh == 144.0
        assert protected == 624.0

    def test_p4_buffer_zero(self, mission_engine):
        """P4 deferrable loads receive zero buffer."""
        buffer_kwh, protected = mission_engine.buffer_engine.calculate_buffer(
            PriorityLevel.P4, base_energy_kwh=50.0
        )
        assert buffer_kwh == 0.0
        assert protected == 50.0


class TestFlexibilityEngine:
    """Test flexibility classification and scheduling window derivations."""

    def test_inflexible_flags(self):
        m = Mission(
            station_id="S", name="ECLS", required_power_kw=45, min_power_kw=35,
            max_power_kw=60, expected_duration_minutes=120, flexibility=Flexibility.INFLEXIBLE,
        )
        profile = FlexibilityEngine.evaluate_flexibility(m)
        assert profile.interruptible is False
        assert profile.shiftable is False
        assert profile.can_curtail_power is False

    def test_partially_flexible_flags(self):
        m = Mission(
            station_id="S", name="Ice Core", required_power_kw=120, min_power_kw=90,
            max_power_kw=150, expected_duration_minutes=240, flexibility=Flexibility.PARTIALLY_FLEXIBLE,
        )
        profile = FlexibilityEngine.evaluate_flexibility(m)
        assert profile.interruptible is False
        assert profile.shiftable is False
        assert profile.can_curtail_power is True
        assert profile.curtailment_potential_kw == 30.0  # 120 - 90

    def test_flexible_latest_start_calculation(self):
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(hours=10)
        m = Mission(
            station_id="S", name="Compute", required_power_kw=100, min_power_kw=60,
            max_power_kw=120, expected_duration_minutes=180,  # 3 hours
            deadline=deadline, flexibility=Flexibility.FLEXIBLE,
        )
        profile = FlexibilityEngine.evaluate_flexibility(m, reference_time=now)
        assert profile.latest_start == deadline - timedelta(hours=3)
