"""
Frost OS Module 01 — Orchestrator Agent.

A deterministic coordinator agent that drives the event-to-action pipeline.
It identifies event type, selects workflow, requests specialist analysis,
aggregates results, and prepares explainable action-plan proposals.

IMPORTANT:
- This agent is DETERMINISTIC — no LLM for control, optimization,
  safety thresholds, or hardware commands.
- The optional generate_summary() method may use an LLM for
  operator-facing natural language summaries ONLY.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.event_router import EventRouter
from app.models.decision import DecisionContext
from app.models.event import StationEvent, Severity

logger = structlog.get_logger(__name__)


class OrchestratorAgent:
    """
    Deterministic orchestrator agent.

    Responsibilities:
    1. Identify event type and severity
    2. Select appropriate workflow
    3. Track which specialist modules are needed
    4. Aggregate and validate module responses
    5. Prepare explainable reasoning chain
    6. Generate human-readable summaries

    This agent does NOT:
    - Use an LLM for electrical control/optimization
    - Make safety threshold decisions
    - Send raw hardware commands
    - Override M07 safety constraints
    """

    def __init__(self, router: EventRouter) -> None:
        self._router = router

    def analyze_event(self, event: StationEvent) -> dict[str, Any]:
        """
        Analyze an incoming event and determine the response plan.

        Returns a structured analysis with workflow selection,
        affected modules, and initial reasoning.
        """
        route = self._router.classify(event)
        effective_severity = self._router.get_severity(event)

        analysis = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "station_id": event.station_id,
            "effective_severity": effective_severity.value,
            "criticality": route.criticality,
            "workflow": route.workflow_name,
            "affected_modules": list(route.affected_modules),
            "requires_immediate_attention": effective_severity in (Severity.HIGH, Severity.CRITICAL),
            "initial_reasoning": self._build_initial_reasoning(event, route),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return analysis

    def validate_context_completeness(self, context: DecisionContext) -> dict[str, Any]:
        """
        Validate that the decision context has sufficient data
        for action plan creation.

        Returns a validation report identifying missing data,
        degraded modules, and overall readiness.
        """
        issues: list[str] = []
        warnings: list[str] = []

        # Check required module responses based on workflow
        required_responses = {
            "energy_analysis": context.energy_analysis,
            "optimization_result": context.optimization_result,
            "reserve_validation": context.reserve_validation,
            "safety_validation": context.safety_validation,
        }

        for name, response in required_responses.items():
            if response is None:
                issues.append(f"Missing {name} — module did not respond")
            elif response.is_degraded:
                warnings.append(f"{name} is degraded — results may be incomplete")
            elif response.status != "success":
                warnings.append(f"{name} returned non-success status: {response.status}")

        is_ready = len(issues) == 0
        confidence = self._assess_confidence(context)

        return {
            "is_ready": is_ready,
            "issues": issues,
            "warnings": warnings,
            "degraded_modules": context.degraded_modules,
            "confidence": confidence,
            "recommendation": (
                "Proceed with plan creation" if is_ready
                else "Cannot create plan — missing critical data"
            ),
        }

    def generate_summary(self, context: DecisionContext, plan: Any = None) -> str:
        """
        Generate a human-readable summary of the decision and plan.

        This is a DETERMINISTIC template-based summary.
        An LLM could enhance this for natural language, but
        it is NOT used for any control decisions.
        """
        parts = [
            f"## Decision Summary",
            f"**Decision ID**: {context.decision_id}",
            f"**Event**: {context.event_type} (Severity: {context.severity.value})",
            f"**Station**: {context.station_id}",
            f"**Workflow**: {context.workflow_name}",
            "",
            "### Analysis Chain",
        ]

        for i, reason in enumerate(context.reasoning, 1):
            parts.append(f"{i}. {reason}")

        if context.degraded_modules:
            parts.append("")
            parts.append(f"### ⚠️ Degraded Modules")
            parts.append(f"The following modules returned incomplete data: {', '.join(context.degraded_modules)}")

        if context.is_emergency:
            parts.append("")
            parts.append("### 🚨 EMERGENCY")
            parts.append("M07 has flagged this as an emergency. Safeguard actions proceed without human authorization.")

        return "\n".join(parts)

    def _build_initial_reasoning(self, event: StationEvent, route: Any) -> list[str]:
        """Build initial reasoning chain for an event."""
        reasoning = [
            f"Received {event.event_type.value} event from {event.source}",
            f"Classified as {route.criticality} criticality",
            f"Selected workflow: {route.workflow_name}",
            f"Consulting modules: {', '.join(route.affected_modules)}",
        ]

        # Event-specific reasoning
        if event.event_type.value in ("WIND_POWER_DROP", "SOLAR_OUTPUT_DROP"):
            payload = event.payload
            if "previous_kw" in payload and "current_kw" in payload:
                drop = payload["previous_kw"] - payload["current_kw"]
                reasoning.append(
                    f"Generation dropped from {payload['previous_kw']} kW "
                    f"to {payload['current_kw']} kW (Δ {drop:.1f} kW)"
                )

        return reasoning

    def _assess_confidence(self, context: DecisionContext) -> float:
        """Assess overall confidence in the decision."""
        scores = []
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
                if response.is_degraded:
                    scores.append(0.3)
                else:
                    scores.append(response.confidence)

        return sum(scores) / len(scores) if scores else 0.0
