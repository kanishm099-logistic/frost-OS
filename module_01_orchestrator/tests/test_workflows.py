"""
Frost OS Module 01 — Workflow Tests.

Tests for workflow registry, workflow handlers, parallel execution,
and dependency ordering.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.core.workflow_engine import WorkflowEngine, WorkflowRegistry
from app.models.event import EventType, Severity, StationEvent
from app.models.decision import DecisionContext, ModuleResponse


# ── Workflow Registry ─────────────────────────────────────────────────

class TestWorkflowRegistry:
    """Test workflow registration and lookup."""

    def test_register_and_lookup(self, workflow_registry):
        """Registered workflow should be retrievable."""
        async def dummy_handler(event, context, clients):
            return context

        workflow_registry.register("test_workflow", dummy_handler)
        assert workflow_registry.has("test_workflow")
        handler = workflow_registry.get("test_workflow")
        assert handler is not None

    def test_lookup_unknown_returns_none(self, workflow_registry):
        """Unknown workflow should return None."""
        assert workflow_registry.get("nonexistent") is None
        assert not workflow_registry.has("nonexistent")

    def test_list_workflows(self, workflow_registry):
        """Should list all registered workflow names."""
        async def handler(e, c, cl): return c
        workflow_registry.register("wf_a", handler)
        workflow_registry.register("wf_b", handler)
        names = workflow_registry.list_workflows()
        assert "wf_a" in names
        assert "wf_b" in names

    def test_overwrite_existing(self, workflow_registry):
        """Registering same name should overwrite."""
        async def handler1(e, c, cl): return c
        async def handler2(e, c, cl): return c
        workflow_registry.register("wf", handler1)
        workflow_registry.register("wf", handler2)
        assert workflow_registry.get("wf") is handler2


# ── Workflow Engine ───────────────────────────────────────────────────

class TestWorkflowEngine:
    """Test workflow engine dispatch."""

    @pytest.mark.asyncio
    async def test_execute_unknown_raises(self, workflow_engine, wind_drop_event):
        """Executing an unregistered workflow should raise ValueError."""
        context = DecisionContext(
            event_id=wind_drop_event.event_id,
            station_id=wind_drop_event.station_id,
            correlation_id=wind_drop_event.correlation_id,
            event_type=wind_drop_event.event_type.value,
            severity=wind_drop_event.severity,
            workflow_name="nonexistent",
        )
        with pytest.raises(ValueError, match="Unknown workflow"):
            await workflow_engine.execute("nonexistent", wind_drop_event, context, None)

    @pytest.mark.asyncio
    async def test_execute_registered_workflow(self, workflow_registry):
        """Should successfully execute a registered workflow."""
        executed = {"called": False}

        async def handler(event, context, clients):
            executed["called"] = True
            context.reasoning.append("test handler executed")
            return context

        workflow_registry.register("test", handler)
        engine = WorkflowEngine(workflow_registry)

        event = StationEvent(
            source="test", event_type=EventType.BATTERY_LOW, station_id="S1"
        )
        context = DecisionContext(
            event_id=event.event_id,
            station_id=event.station_id,
            correlation_id=event.correlation_id,
            event_type=event.event_type.value,
            severity=event.severity,
            workflow_name="test",
        )

        result = await engine.execute("test", event, context, None)
        assert executed["called"]
        assert "test handler executed" in result.reasoning


# ── Generation Drop Workflow ──────────────────────────────────────────

class TestGenerationDropWorkflow:
    """Test the generation_drop workflow handler."""

    @pytest.mark.asyncio
    async def test_populates_all_module_responses(
        self, wind_drop_event, mock_clients
    ):
        """Workflow should populate energy, forecast, diagnostic, mission, optimizer, reserve, safety."""
        from app.workflows.generation_drop import generation_drop_workflow

        context = DecisionContext(
            event_id=wind_drop_event.event_id,
            station_id=wind_drop_event.station_id,
            correlation_id=wind_drop_event.correlation_id,
            event_type=wind_drop_event.event_type.value,
            severity=wind_drop_event.severity,
            workflow_name="generation_drop",
        )

        result = await generation_drop_workflow(wind_drop_event, context, mock_clients)

        assert result.energy_analysis is not None
        assert result.forecast_analysis is not None
        assert result.diagnostic_analysis is not None
        assert result.mission_analysis is not None
        assert result.optimization_result is not None
        assert result.reserve_validation is not None
        assert result.safety_validation is not None

    @pytest.mark.asyncio
    async def test_reasoning_chain_populated(
        self, wind_drop_event, mock_clients
    ):
        """Workflow should produce a non-empty reasoning chain."""
        from app.workflows.generation_drop import generation_drop_workflow

        context = DecisionContext(
            event_id=wind_drop_event.event_id,
            station_id=wind_drop_event.station_id,
            correlation_id=wind_drop_event.correlation_id,
            event_type=wind_drop_event.event_type.value,
            severity=wind_drop_event.severity,
            workflow_name="generation_drop",
        )

        result = await generation_drop_workflow(wind_drop_event, context, mock_clients)
        assert len(result.reasoning) > 0

    @pytest.mark.asyncio
    async def test_non_emergency_by_default(
        self, wind_drop_event, mock_clients
    ):
        """Standard wind drop should not be flagged as emergency."""
        from app.workflows.generation_drop import generation_drop_workflow

        context = DecisionContext(
            event_id=wind_drop_event.event_id,
            station_id=wind_drop_event.station_id,
            correlation_id=wind_drop_event.correlation_id,
            event_type=wind_drop_event.event_type.value,
            severity=wind_drop_event.severity,
            workflow_name="generation_drop",
        )

        result = await generation_drop_workflow(wind_drop_event, context, mock_clients)
        assert result.is_emergency is False


# ── Mission Start Workflow ────────────────────────────────────────────

class TestMissionStartWorkflow:
    """Test the mission_start workflow handler."""

    @pytest.mark.asyncio
    async def test_populates_mission_and_energy(
        self, mission_started_event, mock_clients
    ):
        """Should populate mission and energy analyses."""
        from app.workflows.mission_start import mission_start_workflow

        context = DecisionContext(
            event_id=mission_started_event.event_id,
            station_id=mission_started_event.station_id,
            correlation_id=mission_started_event.correlation_id,
            event_type=mission_started_event.event_type.value,
            severity=mission_started_event.severity,
            workflow_name="mission_start",
        )

        result = await mission_start_workflow(mission_started_event, context, mock_clients)
        assert result.mission_analysis is not None
        assert result.energy_analysis is not None
        assert result.optimization_result is not None
