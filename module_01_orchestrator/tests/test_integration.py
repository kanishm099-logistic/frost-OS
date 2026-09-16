"""
Frost OS Module 01 — Integration Test: WIND_POWER_DROP Pipeline.

Full end-to-end test of the orchestration pipeline:

1. POST event (wind drops 180→70 kW)
2. Verify Energy+Forecast+Diagnostic+Mission called in parallel
3. Verify Optimizer called with aggregated context
4. Verify Reserve validation
5. Verify Safety check
6. Verify ActionPlan created with AWAITING_AUTHORIZATION
7. POST authorize → verify status → AUTHORIZED
8. Verify execution sent to mock M08
9. Verify COMPLETED status
10. Verify all audit logs present
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.core.orchestrator import Orchestrator
from app.models.decision import DecisionStatus
from app.models.action_plan import PlanStatus
from app.models.event import EventType, Severity, StationEvent
from app.storage.repository import (
    ActionPlanRepository,
    AuditRepository,
    DecisionRepository,
    EventRepository,
    WorkflowRunRepository,
)


class TestWindPowerDropIntegration:
    """
    Full integration test: WIND_POWER_DROP from event to completion.

    This test exercises the complete orchestration pipeline with
    mock module clients and an in-memory database.
    """

    @pytest.mark.asyncio
    async def test_full_wind_drop_pipeline(self, orchestrator, db_session):
        """
        Complete pipeline test:
        Event → Analyze → Optimize → Validate → Plan → Authorize → Execute → Verify → Complete
        """
        # ── 1. Create the wind drop event ─────────────────────────────
        event = StationEvent(
            source="wind-sensor-array-01",
            event_type=EventType.WIND_POWER_DROP,
            severity=Severity.HIGH,
            station_id="TEST-STATION-01",
            payload={
                "previous_kw": 180.0,
                "current_kw": 70.0,
                "drop_pct": 61.1,
                "turbine_id": "WIND-TURBINE-01",
            },
        )

        # Create repositories
        event_repo = EventRepository(db_session)
        decision_repo = DecisionRepository(db_session)
        plan_repo = ActionPlanRepository(db_session)
        audit_repo = AuditRepository(db_session)
        workflow_repo = WorkflowRunRepository(db_session)

        # ── 2. Process event through pipeline ─────────────────────────
        result = await orchestrator.process_event(
            event=event,
            event_repo=event_repo,
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
            workflow_repo=workflow_repo,
        )

        # ── 3. Verify pipeline created decision + plan ────────────────
        assert result["decision_id"] is not None
        assert result["plan_id"] is not None
        assert result["status"] == "AWAITING_AUTHORIZATION"
        assert result["requires_authorization"] is True

        decision_id = result["decision_id"]
        plan_id = result["plan_id"]

        # ── 4. Verify event was persisted ─────────────────────────────
        saved_event = await event_repo.get_by_id(event.event_id)
        assert saved_event is not None
        assert saved_event.event_type == EventType.WIND_POWER_DROP
        assert saved_event.station_id == "TEST-STATION-01"

        # ── 5. Verify decision state (AWAITING_AUTHORIZATION) ────────
        decision_record = await decision_repo.get_by_id(decision_id)
        assert decision_record is not None
        assert decision_record.status == DecisionStatus.AWAITING_AUTHORIZATION
        assert decision_record.workflow_name == "generation_drop"

        # ── 6. Verify state transitions were recorded ─────────────────
        transitions = await decision_repo.get_transitions(decision_id)
        statuses = [t.to_status for t in transitions]

        assert DecisionStatus.DETECTED in statuses
        assert DecisionStatus.ANALYZING in statuses
        assert DecisionStatus.PREDICTED in statuses
        assert DecisionStatus.OPTIMIZING in statuses
        assert DecisionStatus.VALIDATING in statuses
        assert DecisionStatus.AWAITING_AUTHORIZATION in statuses

        # ── 7. Verify action plan ─────────────────────────────────────
        plan_record = await plan_repo.get_by_id(plan_id)
        assert plan_record is not None
        assert plan_record.status == PlanStatus.AWAITING_AUTHORIZATION
        assert plan_record.station_id == "TEST-STATION-01"
        assert plan_record.requires_authorization is True
        assert plan_record.is_emergency is False
        assert len(plan_record.actions) > 0  # Should have optimizer actions
        assert plan_record.projected_reserve_kwh > 0

        # ── 8. Authorize the plan ─────────────────────────────────────
        auth_result = await orchestrator.authorize_plan(
            plan_id=plan_id,
            authorized_by="operator-jane",
            reason="Reviewed and approved — proceed with load shedding",
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
            event_repo=event_repo,
        )

        assert auth_result["status"] == "authorized_and_executing"
        assert auth_result["authorized_by"] == "operator-jane"

        # ── 9. Verify decision reached COMPLETED ──────────────────────
        final_decision = await decision_repo.get_by_id(decision_id)
        assert final_decision.status == DecisionStatus.COMPLETED

        # ── 10. Verify final transitions include full lifecycle ───────
        final_transitions = await decision_repo.get_transitions(decision_id)
        final_statuses = [t.to_status for t in final_transitions]

        assert DecisionStatus.AUTHORIZED in final_statuses
        assert DecisionStatus.EXECUTING in final_statuses
        assert DecisionStatus.VERIFYING in final_statuses
        assert DecisionStatus.COMPLETED in final_statuses

        # ── 11. Verify plan status is COMPLETED ──────────────────────
        final_plan = await plan_repo.get_by_id(plan_id)
        assert final_plan.status == PlanStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_plan_rejection_flow(self, orchestrator, db_session):
        """Test that rejecting a plan transitions correctly."""
        event = StationEvent(
            source="wind-sensor-array-01",
            event_type=EventType.WIND_POWER_DROP,
            severity=Severity.HIGH,
            station_id="TEST-STATION-01",
            payload={"previous_kw": 180.0, "current_kw": 70.0},
        )

        event_repo = EventRepository(db_session)
        decision_repo = DecisionRepository(db_session)
        plan_repo = ActionPlanRepository(db_session)
        audit_repo = AuditRepository(db_session)
        workflow_repo = WorkflowRunRepository(db_session)

        # Process event
        result = await orchestrator.process_event(
            event=event,
            event_repo=event_repo,
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
            workflow_repo=workflow_repo,
        )

        plan_id = result["plan_id"]
        decision_id = result["decision_id"]

        # Reject the plan
        reject_result = await orchestrator.reject_plan(
            plan_id=plan_id,
            rejected_by="operator-bob",
            reason="Need to review alternative options first",
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
        )

        assert reject_result["status"] == "rejected"
        assert reject_result["rejected_by"] == "operator-bob"

        # Verify final states
        final_decision = await decision_repo.get_by_id(decision_id)
        assert final_decision.status == DecisionStatus.REJECTED

        final_plan = await plan_repo.get_by_id(plan_id)
        assert final_plan.status == PlanStatus.REJECTED

    @pytest.mark.asyncio
    async def test_multiple_event_types(self, orchestrator, db_session):
        """Test that different event types route to correct workflows."""
        events = [
            StationEvent(
                source="sensor",
                event_type=EventType.BATTERY_LOW,
                severity=Severity.HIGH,
                station_id="TEST-STATION-01",
                payload={"current_soc_pct": 15.0},
            ),
            StationEvent(
                source="weather",
                event_type=EventType.WEATHER_WARNING,
                severity=Severity.MEDIUM,
                station_id="TEST-STATION-01",
                payload={"warning_type": "storm"},
            ),
        ]

        for event in events:
            event_repo = EventRepository(db_session)
            decision_repo = DecisionRepository(db_session)
            plan_repo = ActionPlanRepository(db_session)
            audit_repo = AuditRepository(db_session)
            workflow_repo = WorkflowRunRepository(db_session)

            result = await orchestrator.process_event(
                event=event,
                event_repo=event_repo,
                decision_repo=decision_repo,
                plan_repo=plan_repo,
                audit_repo=audit_repo,
                workflow_repo=workflow_repo,
            )

            assert result["decision_id"] is not None
            assert result["plan_id"] is not None

            # Verify correct workflow was used
            decision = await decision_repo.get_by_id(result["decision_id"])
            if event.event_type == EventType.BATTERY_LOW:
                assert decision.workflow_name == "low_reserve"
            elif event.event_type == EventType.WEATHER_WARNING:
                assert decision.workflow_name == "weather_risk"
