"""
Frost OS Module 01 — Decision Manager.

Manages the decision lifecycle: state machine enforcement,
authorization flow, emergency bypass, and action plan creation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.models.action_plan import (
    ActionPlan,
    Authorization,
    AuthorizationDecision,
    PlannedAction,
    PlanStatus,
    SafetyStatus,
)
from app.models.decision import (
    Decision,
    DecisionContext,
    DecisionStatus,
    ModuleResponse,
    validate_transition,
)
from app.models.event import StationEvent
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class DecisionManager:
    """
    Manages the decision lifecycle and action plan creation.

    Responsibilities:
    - Create decisions from events
    - Enforce state machine transitions
    - Build action plans from optimization results
    - Handle authorization (approve/reject)
    - Handle emergency bypass (M07 emergency flag)
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_decision(
        self,
        event: StationEvent,
        workflow_name: str,
    ) -> Decision:
        """Create a new decision from an event."""
        decision_id = str(uuid.uuid4())
        context = DecisionContext(
            decision_id=decision_id,
            event_id=event.event_id,
            station_id=event.station_id,
            correlation_id=event.correlation_id,
            event_type=event.event_type.value,
            severity=event.severity,
            workflow_name=workflow_name,
        )

        return Decision(
            decision_id=decision_id,
            event_id=event.event_id,
            station_id=event.station_id,
            correlation_id=event.correlation_id,
            status=DecisionStatus.DETECTED,
            workflow_name=workflow_name,
            context=context,
        )

    def build_action_plan(
        self,
        decision: Decision,
        context: DecisionContext,
        event: StationEvent,
    ) -> ActionPlan:
        """
        Build an action plan from the decision context.

        Extracts optimization results, safety validation, and
        reserve information to create a structured plan.
        """
        # Extract optimization actions
        actions: list[PlannedAction] = []
        projected_reserve = 0.0
        required_reserve = 0.0

        if context.optimization_result and context.optimization_result.status == "success":
            opt_data = context.optimization_result.data.get("optimization_result", {})
            for action_data in opt_data.get("actions", []):
                actions.append(PlannedAction(
                    action_type=action_data.get("action_type", "UNKNOWN"),
                    target=action_data.get("target", "unknown"),
                    description=action_data.get("description", ""),
                    parameters=action_data.get("parameters", {}),
                    priority=action_data.get("priority", 0),
                    estimated_impact_kwh=action_data.get("estimated_impact_kwh", 0.0),
                    reversible=action_data.get("reversible", True),
                ))
            projected_reserve = opt_data.get("projected_reserve_kwh", 0.0)

        # Extract reserve requirements
        if context.reserve_validation and context.reserve_validation.status == "success":
            reserve_data = context.reserve_validation.data.get("reserve_validation", {})
            required_reserve = reserve_data.get("required_reserve_kwh", 200.0)
            if projected_reserve == 0.0:
                projected_reserve = reserve_data.get("projected_reserve_kwh", 0.0)

        # Determine safety status
        safety_status = SafetyStatus.PASSED
        is_emergency = context.is_emergency
        if context.safety_validation and context.safety_validation.status == "success":
            safety_data = context.safety_validation.data.get("safety_check", {})
            if not safety_data.get("is_safe", True):
                safety_status = SafetyStatus.FAILED
            if safety_data.get("is_emergency", False):
                is_emergency = True
                safety_status = SafetyStatus.EMERGENCY_OVERRIDE

        # Build explanation
        reasoning_parts = [f"Event: {event.event_type.value} at {event.station_id}"]
        reasoning_parts.extend(context.reasoning)
        if context.degraded_modules:
            reasoning_parts.append(
                f"Degraded modules (results may be incomplete): {', '.join(context.degraded_modules)}"
            )

        reason = "; ".join(reasoning_parts)

        # Emergency plans don't need authorization
        requires_authorization = not is_emergency

        plan = ActionPlan(
            plan_id=str(uuid.uuid4()),
            trigger_event_id=event.event_id,
            decision_id=decision.decision_id,
            station_id=event.station_id,
            status=PlanStatus.AWAITING_AUTHORIZATION if requires_authorization else PlanStatus.AUTHORIZED,
            reason=reason,
            actions=actions,
            projected_reserve_kwh=projected_reserve,
            required_reserve_kwh=required_reserve,
            safety_status=safety_status,
            requires_authorization=requires_authorization,
            is_emergency=is_emergency,
            expires_at=datetime.now(timezone.utc) + timedelta(
                minutes=self._settings.action_plan_expiry_minutes
            ),
            metadata={
                "workflow": decision.workflow_name,
                "event_severity": event.severity.value,
                "degraded_modules": context.degraded_modules,
                "confidence": self._compute_confidence(context),
            },
        )

        return plan

    def create_authorization(
        self,
        plan_id: str,
        decision: AuthorizationDecision,
        authorized_by: str,
        reason: str = "",
    ) -> Authorization:
        """Create an authorization record."""
        return Authorization(
            plan_id=plan_id,
            decision=decision,
            authorized_by=authorized_by,
            reason=reason,
        )

    def _compute_confidence(self, context: DecisionContext) -> float:
        """
        Compute overall decision confidence from module responses.

        Averages confidence scores, penalizing degraded/missing modules.
        """
        scores: list[float] = []
        for response in [
            context.energy_analysis,
            context.forecast_analysis,
            context.diagnostic_analysis,
            context.mission_analysis,
            context.optimization_result,
            context.reserve_validation,
            context.safety_validation,
        ]:
            if response is not None:
                if response.is_degraded or response.status != "success":
                    scores.append(0.3)  # Penalty for degraded
                else:
                    scores.append(response.confidence)

        return sum(scores) / len(scores) if scores else 0.0
