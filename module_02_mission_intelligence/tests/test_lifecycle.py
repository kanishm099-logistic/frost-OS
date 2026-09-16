"""
Frost OS Module 02 — Mission Lifecycle & Dependency Tests.

Tests the state machine, prerequisite DAG dependencies,
and state transition persistence.
"""

from __future__ import annotations

import pytest

from app.models.mission import Flexibility, Mission, MissionState, MissionType
from app.models.priority import PriorityLevel
from app.storage.repository import MissionRepository


class TestMissionLifecycle:
    """Test state machine progression and transition rules."""

    def test_full_lifecycle_path(self, mission_engine):
        m = Mission(
            station_id="STN", name="Workflow Mission",
            required_power_kw=50, min_power_kw=40, max_power_kw=60,
            expected_duration_minutes=60, status=MissionState.CREATED,
        )

        # CREATED -> CLASSIFYING
        ok, _ = mission_engine.validate_transition(m, MissionState.CLASSIFYING)
        assert ok is True
        m.status = MissionState.CLASSIFYING

        # CLASSIFYING -> SCHEDULED
        ok, _ = mission_engine.validate_transition(m, MissionState.SCHEDULED)
        assert ok is True
        m.status = MissionState.SCHEDULED

        # SCHEDULED -> READY
        ok, _ = mission_engine.validate_transition(m, MissionState.READY)
        assert ok is True
        m.status = MissionState.READY

        # READY -> RUNNING
        ok, _ = mission_engine.validate_transition(m, MissionState.RUNNING)
        assert ok is True
        m.status = MissionState.RUNNING

        # RUNNING -> PAUSED
        ok, _ = mission_engine.validate_transition(m, MissionState.PAUSED)
        assert ok is True
        m.status = MissionState.PAUSED

        # PAUSED -> RUNNING
        ok, _ = mission_engine.validate_transition(m, MissionState.RUNNING)
        assert ok is True
        m.status = MissionState.RUNNING

        # RUNNING -> COMPLETED
        ok, _ = mission_engine.validate_transition(m, MissionState.COMPLETED)
        assert ok is True
        m.status = MissionState.COMPLETED

        # COMPLETED is terminal
        ok_terminal, _ = mission_engine.validate_transition(m, MissionState.RUNNING)
        assert ok_terminal is False


class TestDependencyEnforcement:
    """
    Test DAG prerequisite dependencies:
    WEATHER_DATA -> RESEARCH_ANALYSIS -> COMPUTE_JOB
    """

    def test_dependency_chain_blocking(self, mission_engine):
        m_weather = Mission(
            mission_id="MSN-WEATHER", station_id="STN", name="Weather Radar",
            required_power_kw=20, min_power_kw=15, max_power_kw=30,
            expected_duration_minutes=60, status=MissionState.RUNNING,
        )

        m_research = Mission(
            mission_id="MSN-RESEARCH", station_id="STN", name="Sample Analysis",
            required_power_kw=40, min_power_kw=30, max_power_kw=50,
            expected_duration_minutes=60, dependencies=["MSN-WEATHER"],
            status=MissionState.SCHEDULED,
        )

        all_missions = {
            m_weather.mission_id: m_weather,
            m_research.mission_id: m_research,
        }

        # 1. MSN-RESEARCH cannot become READY because MSN-WEATHER is RUNNING (not COMPLETED)
        can_start, msg = mission_engine.validate_transition(
            m_research, MissionState.READY, all_missions
        )
        assert can_start is False
        assert "prerequisite dependencies not completed" in msg
        assert "MSN-WEATHER" in msg

        # 2. Mark MSN-WEATHER as COMPLETED
        m_weather.status = MissionState.COMPLETED

        # 3. Now MSN-RESEARCH can transition to READY and RUNNING
        can_ready, _ = mission_engine.validate_transition(
            m_research, MissionState.READY, all_missions
        )
        assert can_ready is True
        m_research.status = MissionState.READY

        can_run, _ = mission_engine.validate_transition(
            m_research, MissionState.RUNNING, all_missions
        )
        assert can_run is True


@pytest.mark.asyncio
class TestTransitionPersistence:
    """Test state transition recording in SQLite database."""

    async def test_transition_audit_logged(self, db_session, sample_p1_mission):
        repo = MissionRepository(db_session)
        await repo.save(sample_p1_mission)

        # Record a state transition
        await repo.record_transition(
            mission_id=sample_p1_mission.mission_id,
            from_state=MissionState.READY,
            to_state=MissionState.RUNNING,
            reason="Operator dispatch authorization",
            actor="dr-sarah-chen",
        )

        # Retrieve transition history
        history = await repo.get_transitions(sample_p1_mission.mission_id)
        assert len(history) == 1
        assert history[0].from_state == MissionState.READY
        assert history[0].to_state == MissionState.RUNNING
        assert history[0].actor == "dr-sarah-chen"
        assert history[0].reason == "Operator dispatch authorization"
