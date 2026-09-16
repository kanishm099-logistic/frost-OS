"""
Frost OS Module 01 — Decision & State Machine Tests.

Tests for state machine transitions, authorization flow,
safety exception bypass, and action plan creation.
"""

from __future__ import annotations

import pytest

from app.models.decision import (
    DecisionStatus,
    VALID_TRANSITIONS,
    validate_transition,
    DecisionContext,
    ModuleResponse,
)
from app.models.action_plan import (
    ActionPlan,
    AuthorizationDecision,
    PlanStatus,
    SafetyStatus,
    PlannedAction,
)
from app.models.event import EventType, Severity, StationEvent
from app.core.decision_manager import DecisionManager


# ── State Machine Transitions ─────────────────────────────────────────

class TestStateMachine:
    """Test decision state machine transition validation."""

    def test_valid_detected_to_analyzing(self):
        assert validate_transition(DecisionStatus.DETECTED, DecisionStatus.ANALYZING)

    def test_valid_analyzing_to_predicted(self):
        assert validate_transition(DecisionStatus.ANALYZING, DecisionStatus.PREDICTED)

    def test_valid_predicted_to_optimizing(self):
        assert validate_transition(DecisionStatus.PREDICTED, DecisionStatus.OPTIMIZING)

    def test_valid_optimizing_to_validating(self):
        assert validate_transition(DecisionStatus.OPTIMIZING, DecisionStatus.VALIDATING)

    def test_valid_validating_to_awaiting(self):
        assert validate_transition(DecisionStatus.VALIDATING, DecisionStatus.AWAITING_AUTHORIZATION)

    def test_valid_validating_to_authorized_emergency(self):
        """Emergency bypass: VALIDATING → AUTHORIZED (skip AWAITING)."""
        assert validate_transition(DecisionStatus.VALIDATING, DecisionStatus.AUTHORIZED)

    def test_valid_awaiting_to_authorized(self):
        assert validate_transition(DecisionStatus.AWAITING_AUTHORIZATION, DecisionStatus.AUTHORIZED)

    def test_valid_awaiting_to_rejected(self):
        assert validate_transition(DecisionStatus.AWAITING_AUTHORIZATION, DecisionStatus.REJECTED)

    def test_valid_authorized_to_executing(self):
        assert validate_transition(DecisionStatus.AUTHORIZED, DecisionStatus.EXECUTING)

    def test_valid_executing_to_verifying(self):
        assert validate_transition(DecisionStatus.EXECUTING, DecisionStatus.VERIFYING)

    def test_valid_verifying_to_completed(self):
        assert validate_transition(DecisionStatus.VERIFYING, DecisionStatus.COMPLETED)

    def test_invalid_detected_to_completed(self):
        """Cannot skip the entire pipeline."""
        assert not validate_transition(DecisionStatus.DETECTED, DecisionStatus.COMPLETED)

    def test_invalid_completed_to_anything(self):
        """COMPLETED is terminal."""
        assert not validate_transition(DecisionStatus.COMPLETED, DecisionStatus.ANALYZING)

    def test_invalid_rejected_to_anything(self):
        """REJECTED is terminal."""
        assert not validate_transition(DecisionStatus.REJECTED, DecisionStatus.AUTHORIZED)

    def test_cancelled_is_terminal(self):
        """CANCELLED is terminal."""
        assert not validate_transition(DecisionStatus.CANCELLED, DecisionStatus.DETECTED)

    def test_can_cancel_from_most_states(self):
        """Most non-terminal states should allow cancellation."""
        cancellable = [
            DecisionStatus.DETECTED,
            DecisionStatus.ANALYZING,
            DecisionStatus.PREDICTED,
            DecisionStatus.OPTIMIZING,
            DecisionStatus.VALIDATING,
        ]
        for state in cancellable:
            assert validate_transition(state, DecisionStatus.CANCELLED), \
                f"Should be able to cancel from {state}"

    def test_execution_failed_to_reoptimizing(self):
        """Should allow retry via reoptimization after failure."""
        assert validate_transition(DecisionStatus.EXECUTION_FAILED, DecisionStatus.REOPTIMIZING)

    def test_all_states_covered(self):
        """Every DecisionStatus should have an entry in VALID_TRANSITIONS."""
        for status in DecisionStatus:
            assert status in VALID_TRANSITIONS, f"Missing transitions for {status}"


# ── Decision Manager ──────────────────────────────────────────────────

class TestDecisionManager:
    """Test DecisionManager operations."""

    def test_create_decision(self, decision_manager, wind_drop_event):
        """Should create a decision with DETECTED status."""
        decision = decision_manager.create_decision(wind_drop_event, "generation_drop")
        assert decision.status == DecisionStatus.DETECTED
        assert decision.event_id == wind_drop_event.event_id
        assert decision.workflow_name == "generation_drop"
        assert decision.context is not None

    def test_build_action_plan(self, decision_manager, wind_drop_event):
        """Should build an action plan from decision context."""
        decision = decision_manager.create_decision(wind_drop_event, "generation_drop")
        context = decision.context

        # Simulate module responses
        context.optimization_result = ModuleResponse(
            module_name="optimizer",
            status="success",
            data={
                "optimization_result": {
                    "actions": [
                        {
                            "action_type": "REDUCE_LOAD",
                            "target": "P3 Workload",
                            "description": "Reduce P3 by 40%",
                            "parameters": {"reduction_kw": 14.0},
                            "priority": 1,
                            "estimated_impact_kwh": 14.0,
                            "reversible": True,
                        },
                    ],
                    "projected_reserve_kwh": 410.0,
                },
            },
        )
        context.reserve_validation = ModuleResponse(
            module_name="reserve",
            status="success",
            data={
                "reserve_validation": {
                    "required_reserve_kwh": 200.0,
                    "projected_reserve_kwh": 410.0,
                },
            },
        )
        context.safety_validation = ModuleResponse(
            module_name="reserve",
            status="success",
            data={
                "safety_check": {
                    "is_safe": True,
                    "is_emergency": False,
                    "safety_status": "PASSED",
                },
            },
        )

        plan = decision_manager.build_action_plan(decision, context, wind_drop_event)

        assert plan.plan_id is not None
        assert plan.trigger_event_id == wind_drop_event.event_id
        assert plan.station_id == wind_drop_event.station_id
        assert len(plan.actions) == 1
        assert plan.actions[0].action_type == "REDUCE_LOAD"
        assert plan.projected_reserve_kwh == 410.0
        assert plan.required_reserve_kwh == 200.0
        assert plan.safety_status == SafetyStatus.PASSED
        assert plan.requires_authorization is True
        assert plan.is_emergency is False

    def test_emergency_plan_skips_authorization(self, decision_manager, wind_drop_event):
        """Emergency plans should not require authorization."""
        decision = decision_manager.create_decision(wind_drop_event, "generation_drop")
        context = decision.context
        context.is_emergency = True

        context.optimization_result = ModuleResponse(
            module_name="optimizer", status="success", data={"optimization_result": {"actions": []}},
        )
        context.reserve_validation = ModuleResponse(
            module_name="reserve", status="success",
            data={"reserve_validation": {"required_reserve_kwh": 200.0}},
        )
        context.safety_validation = ModuleResponse(
            module_name="reserve", status="success",
            data={"safety_check": {"is_safe": True, "is_emergency": True, "safety_status": "EMERGENCY_OVERRIDE"}},
        )

        plan = decision_manager.build_action_plan(decision, context, wind_drop_event)

        assert plan.is_emergency is True
        assert plan.requires_authorization is False
        assert plan.status == PlanStatus.AUTHORIZED  # Auto-authorized

    def test_authorization_creation(self, decision_manager):
        """Should create a properly structured authorization."""
        auth = decision_manager.create_authorization(
            plan_id="plan-123",
            decision=AuthorizationDecision.APPROVED,
            authorized_by="operator-jane",
            reason="Looks good",
        )
        assert auth.plan_id == "plan-123"
        assert auth.decision == AuthorizationDecision.APPROVED
        assert auth.authorized_by == "operator-jane"
        assert auth.reason == "Looks good"
