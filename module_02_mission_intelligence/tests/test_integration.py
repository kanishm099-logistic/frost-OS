"""
Frost OS Module 02 — End-to-End Integration Tests.

Verifies the complete mission pipeline:
Mission Input -> Classify -> Prioritize -> Estimate Energy ->
Determine Flexibility -> Calculate Buffer -> Create Profile ->
Publish Event -> State Transitions -> Audit Trail.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from app.events.event_types import MissionEventType
from app.models.mission import (
    Flexibility,
    Mission,
    MissionState,
    MissionType,
)
from app.models.priority import PriorityLevel
from app.storage.repository import AuditRepository, MissionRepository


@pytest.mark.asyncio
class TestFullMissionPipeline:
    """End-to-end integration test of Module 02 capabilities."""

    async def test_complete_ice_core_pipeline(
        self,
        db_session,
        mission_engine,
        mission_agent,
        publisher,
    ):
        repo = MissionRepository(db_session)
        audit = AuditRepository(db_session)
        now = datetime.now(timezone.utc)

        # 1. Mission Input & Classification
        raw_text = "Ice Core spectrometry analysis for paleoclimate gases"
        classification = mission_engine.classifier.classify(raw_text)
        assert classification.mission_type == MissionType.RESEARCH
        assert classification.suggested_priority == PriorityLevel.P1

        # 2. Instantiate Mission
        mission = Mission(
            station_id="FROST-STATION-ALPHA",
            name="Ice Core Analysis",
            description=raw_text,
            type=classification.mission_type,
            priority=classification.suggested_priority,
            required_power_kw=120.0,
            min_power_kw=90.0,
            max_power_kw=150.0,
            expected_duration_minutes=240,  # 4 hours
            deadline=now + timedelta(hours=18),
            flexibility=Flexibility.PARTIALLY_FLEXIBLE,
            status=MissionState.SCHEDULED,
        )

        # 3. Enrich Energy & Buffers
        enriched = mission_engine.enrich_mission(mission)
        assert enriched.energy_required_kwh == 480.0
        assert enriched.buffer_kwh == 144.0
        assert enriched.protected_energy_kwh == 624.0

        # 4. Enforce Safety Constraint (Allocating 70 kW must be rejected)
        valid_bad, bad_msg = mission_engine.energy_estimator.validate_power_allocation(
            enriched, proposed_kw=70.0
        )
        assert valid_bad is False
        assert "SAFETY VIOLATION" in bad_msg

        # Allocating 90 kW must be accepted
        valid_ok, ok_msg = mission_engine.energy_estimator.validate_power_allocation(
            enriched, proposed_kw=90.0
        )
        assert valid_ok is True

        # 5. Persist to Database
        await repo.save(enriched)
        await audit.log(
            station_id=enriched.station_id,
            actor="pipeline-test",
            action="mission_created",
            correlation_id="corr-test-01",
            mission_id=enriched.mission_id,
        )

        # 6. Generate Profile for Module 06
        profile = mission_engine.create_profile(enriched, reference_time=now)
        assert profile.mission_id == enriched.mission_id
        assert profile.required_power_kw == 120.0
        assert profile.min_power_kw == 90.0
        assert profile.protected_energy_kwh == 624.0
        assert profile.is_protected is True
        assert profile.scheduling_score >= 80.0

        # 7. Agent Explains Profile
        explanation = mission_agent.explain_mission_profile(profile)
        assert "+30.0%" in explanation["energy_summary"]["buffer_percentage"]
        assert explanation["power_envelope"]["curtailment_room_kw"] == 30.0

        # 8. Publish Lifecycle Events
        msg_id = await publisher.publish_lifecycle(
            event_type=MissionEventType.MISSION_CREATED,
            station_id=enriched.station_id,
            mission_id=enriched.mission_id,
            correlation_id="corr-test-01",
            payload={"name": enriched.name, "priority": enriched.priority.value},
        )
        assert msg_id is not None
        assert len(publisher.published_events) == 1

        # 9. Advance Lifecycle: SCHEDULED -> READY -> RUNNING -> COMPLETED
        can_ready, _ = mission_engine.validate_transition(enriched, MissionState.READY)
        assert can_ready is True
        enriched.status = MissionState.READY
        await repo.update(enriched)
        await repo.record_transition(enriched.mission_id, MissionState.SCHEDULED, MissionState.READY)

        can_run, _ = mission_engine.validate_transition(enriched, MissionState.RUNNING)
        assert can_run is True
        enriched.status = MissionState.RUNNING
        await repo.update(enriched)
        await repo.record_transition(enriched.mission_id, MissionState.READY, MissionState.RUNNING)

        can_complete, _ = mission_engine.validate_transition(enriched, MissionState.COMPLETED)
        assert can_complete is True
        enriched.status = MissionState.COMPLETED
        await repo.update(enriched)
        await repo.record_transition(enriched.mission_id, MissionState.RUNNING, MissionState.COMPLETED)

        # 10. Audit Trail Verification
        transitions = await repo.get_transitions(enriched.mission_id)
        assert len(transitions) == 3
        assert transitions[0].to_state == MissionState.READY
        assert transitions[1].to_state == MissionState.RUNNING
        assert transitions[2].to_state == MissionState.COMPLETED

        logs = await audit.list_logs(station_id=enriched.station_id)
        assert len(logs) >= 1
        assert logs[0].action == "mission_created"
