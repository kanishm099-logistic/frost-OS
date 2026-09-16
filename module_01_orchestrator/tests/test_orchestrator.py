"""
Frost OS Module 01 — Orchestrator Tests.

Tests for the full pipeline with mocks, partial failure handling,
and the orchestrator agent.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.core.orchestrator import Orchestrator
from app.models.decision import DecisionStatus
from app.models.event import EventType, Severity, StationEvent
from app.storage.repository import (
    ActionPlanRepository,
    AuditRepository,
    DecisionRepository,
    EventRepository,
    WorkflowRunRepository,
)
from app.agents.orchestrator_agent import OrchestratorAgent


# ── Orchestrator Agent ────────────────────────────────────────────────

class TestOrchestratorAgent:
    """Test the deterministic orchestrator agent."""

    def test_analyze_event(self, event_router, wind_drop_event):
        """Agent should analyze event and return structured analysis."""
        agent = OrchestratorAgent(event_router)
        analysis = agent.analyze_event(wind_drop_event)

        assert analysis["event_type"] == "WIND_POWER_DROP"
        assert analysis["workflow"] == "generation_drop"
        assert "energy" in analysis["affected_modules"]
        assert analysis["requires_immediate_attention"] is True

    def test_analyze_low_severity_event(self, event_router, mission_started_event):
        """LOW severity event should not require immediate attention."""
        agent = OrchestratorAgent(event_router)
        analysis = agent.analyze_event(mission_started_event)

        assert analysis["requires_immediate_attention"] is False

    def test_initial_reasoning_includes_payload_info(self, event_router):
        """Agent should include payload details in reasoning."""
        event = StationEvent(
            source="sensor-01",
            event_type=EventType.WIND_POWER_DROP,
            severity=Severity.HIGH,
            station_id="STATION-01",
            payload={"previous_kw": 180.0, "current_kw": 70.0},
        )
        agent = OrchestratorAgent(event_router)
        analysis = agent.analyze_event(event)

        reasoning = analysis["initial_reasoning"]
        # Should mention the power drop
        has_drop_info = any("180" in r and "70" in r for r in reasoning)
        assert has_drop_info


# ── Full Pipeline ─────────────────────────────────────────────────────

class TestOrchestratorPipeline:
    """Test the orchestrator's full event processing pipeline."""

    @pytest.mark.asyncio
    async def test_process_event_creates_decision_and_plan(
        self, orchestrator, wind_drop_event, db_session
    ):
        """Processing an event should create a decision and action plan."""
        event_repo = EventRepository(db_session)
        decision_repo = DecisionRepository(db_session)
        plan_repo = ActionPlanRepository(db_session)
        audit_repo = AuditRepository(db_session)
        workflow_repo = WorkflowRunRepository(db_session)

        result = await orchestrator.process_event(
            event=wind_drop_event,
            event_repo=event_repo,
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
            workflow_repo=workflow_repo,
        )

        assert "decision_id" in result
        assert "plan_id" in result
        assert result["status"] == DecisionStatus.AWAITING_AUTHORIZATION.value
        assert result["requires_authorization"] is True

    @pytest.mark.asyncio
    async def test_event_persisted(
        self, orchestrator, wind_drop_event, db_session
    ):
        """Processed event should be persisted to database."""
        event_repo = EventRepository(db_session)
        decision_repo = DecisionRepository(db_session)
        plan_repo = ActionPlanRepository(db_session)
        audit_repo = AuditRepository(db_session)
        workflow_repo = WorkflowRunRepository(db_session)

        await orchestrator.process_event(
            event=wind_drop_event,
            event_repo=event_repo,
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
            workflow_repo=workflow_repo,
        )

        # Verify event is in DB
        saved_event = await event_repo.get_by_id(wind_drop_event.event_id)
        assert saved_event is not None
        assert saved_event.event_type == EventType.WIND_POWER_DROP

    @pytest.mark.asyncio
    async def test_decision_transitions_recorded(
        self, orchestrator, wind_drop_event, db_session
    ):
        """All state transitions should be recorded."""
        event_repo = EventRepository(db_session)
        decision_repo = DecisionRepository(db_session)
        plan_repo = ActionPlanRepository(db_session)
        audit_repo = AuditRepository(db_session)
        workflow_repo = WorkflowRunRepository(db_session)

        result = await orchestrator.process_event(
            event=wind_drop_event,
            event_repo=event_repo,
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
            workflow_repo=workflow_repo,
        )

        transitions = await decision_repo.get_transitions(result["decision_id"])
        statuses = [t.to_status for t in transitions]

        # Should have transitions: DETECTED, ANALYZING, PREDICTED, OPTIMIZING, VALIDATING, AWAITING
        assert DecisionStatus.DETECTED in statuses
        assert DecisionStatus.ANALYZING in statuses
        assert DecisionStatus.AWAITING_AUTHORIZATION in statuses
