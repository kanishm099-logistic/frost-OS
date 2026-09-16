"""
Frost OS Module 02 — Model Validation Tests.

Tests field constraints, envelope validation, timezone enforcement,
and state transition rules.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from app.models.energy_requirement import PowerRequirement
from app.models.mission import (
    Flexibility,
    Mission,
    MissionRecord,
    MissionState,
    MissionType,
    validate_mission_transition,
)
from app.models.priority import PriorityLevel


class TestMissionValidation:
    """Test constraints on the Mission domain model."""

    def test_valid_mission_creation(self):
        """Verify standard valid mission attributes."""
        m = Mission(
            station_id="STN-01",
            name="Atmospheric Sensor Calibration",
            required_power_kw=15.0,
            min_power_kw=10.0,
            max_power_kw=20.0,
            expected_duration_minutes=60,
            flexibility=Flexibility.PARTIALLY_FLEXIBLE,
        )
        assert m.name == "Atmospheric Sensor Calibration"
        assert m.status == MissionState.CREATED
        assert m.priority == PriorityLevel.P2

    def test_rejects_empty_name(self):
        """Names with only whitespace must be rejected."""
        with pytest.raises(ValidationError):
            Mission(
                station_id="STN-01",
                name="   ",
                required_power_kw=15.0,
                min_power_kw=10.0,
                max_power_kw=20.0,
                expected_duration_minutes=60,
            )

    def test_rejects_min_greater_than_required(self):
        """min_power_kw cannot exceed required_power_kw."""
        with pytest.raises(ValidationError, match="cannot exceed required_power_kw"):
            Mission(
                station_id="STN-01",
                name="Invalid Bounds",
                required_power_kw=50.0,
                min_power_kw=60.0,  # Invalid: min > required
                max_power_kw=70.0,
                expected_duration_minutes=60,
            )

    def test_rejects_required_greater_than_max(self):
        """required_power_kw cannot exceed max_power_kw."""
        with pytest.raises(ValidationError, match="cannot exceed max_power_kw"):
            Mission(
                station_id="STN-01",
                name="Invalid Bounds",
                required_power_kw=80.0,
                min_power_kw=50.0,
                max_power_kw=70.0,  # Invalid: required > max
                expected_duration_minutes=60,
            )

    def test_rejects_non_positive_power(self):
        """Power values must be strictly greater than zero."""
        with pytest.raises(ValidationError):
            Mission(
                station_id="STN-01",
                name="Negative Power",
                required_power_kw=-10.0,
                min_power_kw=5.0,
                max_power_kw=20.0,
                expected_duration_minutes=60,
            )

    def test_rejects_zero_duration(self):
        """Duration must be greater than zero."""
        with pytest.raises(ValidationError):
            Mission(
                station_id="STN-01",
                name="Zero Duration",
                required_power_kw=10.0,
                min_power_kw=5.0,
                max_power_kw=20.0,
                expected_duration_minutes=0,
            )

    def test_normalizes_naive_timezone_to_utc(self):
        """Naive timestamps must be automatically normalized to UTC."""
        naive_dt = datetime(2026, 9, 16, 12, 0, 0)
        m = Mission(
            station_id="STN-01",
            name="Naive Timezone",
            required_power_kw=10.0,
            min_power_kw=5.0,
            max_power_kw=20.0,
            expected_duration_minutes=60,
            deadline=naive_dt,
        )
        assert m.deadline.tzinfo == timezone.utc


class TestPriorityRules:
    """Test priority level ranks and protection flags."""

    def test_p0_and_p1_protected(self):
        """P0 and P1 workloads must be identified as protected."""
        assert PriorityLevel.P0.is_protected is True
        assert PriorityLevel.P1.is_protected is True
        assert PriorityLevel.P2.is_protected is False
        assert PriorityLevel.P3.is_protected is False
        assert PriorityLevel.P4.is_protected is False

    def test_priority_ranks(self):
        """Verify priority rank ordering."""
        assert PriorityLevel.P0.rank < PriorityLevel.P1.rank
        assert PriorityLevel.P1.rank < PriorityLevel.P2.rank
        assert PriorityLevel.P2.rank < PriorityLevel.P3.rank
        assert PriorityLevel.P3.rank < PriorityLevel.P4.rank


class TestStateTransitions:
    """Test state machine transition validity."""

    def test_valid_transitions(self):
        """Verify legal state steps."""
        assert validate_mission_transition(MissionState.CREATED, MissionState.CLASSIFYING) is True
        assert validate_mission_transition(MissionState.CLASSIFYING, MissionState.SCHEDULED) is True
        assert validate_mission_transition(MissionState.SCHEDULED, MissionState.READY) is True
        assert validate_mission_transition(MissionState.READY, MissionState.RUNNING) is True
        assert validate_mission_transition(MissionState.RUNNING, MissionState.PAUSED) is True
        assert validate_mission_transition(MissionState.PAUSED, MissionState.RUNNING) is True
        assert validate_mission_transition(MissionState.RUNNING, MissionState.COMPLETED) is True

    def test_invalid_transitions(self):
        """Verify illegal jumps are rejected."""
        assert validate_mission_transition(MissionState.CREATED, MissionState.RUNNING) is False
        assert validate_mission_transition(MissionState.COMPLETED, MissionState.RUNNING) is False
        assert validate_mission_transition(MissionState.CANCELLED, MissionState.READY) is False


class TestORMConversion:
    """Test lossless conversion between domain model and ORM entity."""

    def test_roundtrip_conversion(self, sample_p1_mission):
        """Convert domain -> ORM -> domain and assert equality."""
        record = MissionRecord.from_domain(sample_p1_mission)
        restored = record.to_domain()

        assert restored.mission_id == sample_p1_mission.mission_id
        assert restored.name == sample_p1_mission.name
        assert restored.priority == sample_p1_mission.priority
        assert restored.required_power_kw == sample_p1_mission.required_power_kw
        assert restored.min_power_kw == sample_p1_mission.min_power_kw
        assert restored.status == sample_p1_mission.status
