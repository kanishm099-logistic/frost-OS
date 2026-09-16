"""
Frost OS Module 01 — Mission Start Workflow.

Handles MISSION_STARTED and MISSION_DEADLINE_APPROACHING events.

Pipeline:
  Mission + Energy (parallel)
  → Optimizer
  → Reserve
  → Safety
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.models.event import StationEvent
from app.models.decision import DecisionContext, ModuleResponse

logger = structlog.get_logger(__name__)


async def mission_start_workflow(
    event: StationEvent,
    context: DecisionContext,
    clients: Any,
) -> DecisionContext:
    """Handle mission start/deadline events."""

    await logger.ainfo(
        "Starting mission_start workflow",
        event_id=event.event_id,
        event_type=event.event_type.value,
    )

    # ── Stage 1: Mission details + Energy status (parallel) ──────────
    context.reasoning.append("Gathering mission details and current energy status")

    mission_task = asyncio.create_task(
        clients.mission.analyze_mission_impact(event.station_id, event)
    )
    energy_task = asyncio.create_task(
        clients.energy.get_energy_status(event.station_id)
    )

    results = await asyncio.gather(mission_task, energy_task, return_exceptions=True)

    for name, result in [("mission", results[0]), ("energy", results[1])]:
        if isinstance(result, Exception):
            context.degraded_modules.append(name)
            result = ModuleResponse(
                module_name=name, status="error",
                error_message=str(result), is_degraded=True, confidence=0.0,
            )
        if name == "mission":
            context.mission_analysis = result
        else:
            context.energy_analysis = result
        if hasattr(result, "is_degraded") and result.is_degraded:
            if name not in context.degraded_modules:
                context.degraded_modules.append(name)

    if context.mission_analysis and context.mission_analysis.status == "success":
        impact = context.mission_analysis.data.get("impact_assessment", {})
        context.reasoning.append(
            f"Mission impact: P1={impact.get('p1_impact', '?')}, "
            f"P2={impact.get('p2_impact', '?')}, P3={impact.get('p3_impact', '?')}"
        )

    # ── Stage 2: Optimizer ───────────────────────────────────────────
    context.reasoning.append("Requesting resource optimization for new mission demands")

    optimizer_context = {
        "event": event.model_dump(mode="json"),
        "mission": context.mission_analysis.data if context.mission_analysis else {},
        "energy": context.energy_analysis.data if context.energy_analysis else {},
        "degraded_modules": context.degraded_modules,
    }
    context.optimization_result = await clients.optimizer.optimize_allocation(
        event.station_id, optimizer_context
    )
    if context.optimization_result.is_degraded:
        context.degraded_modules.append("optimizer")

    # ── Stage 3: Reserve + Safety ────────────────────────────────────
    plan_data = {
        "optimization": context.optimization_result.data if context.optimization_result else {},
        "event_type": event.event_type.value,
    }
    context.reserve_validation = await clients.reserve.validate_reserves(
        event.station_id, plan_data
    )
    context.safety_validation = await clients.reserve.check_safety(
        event.station_id, plan_data
    )

    if context.safety_validation and context.safety_validation.status == "success":
        safety_data = context.safety_validation.data.get("safety_check", {})
        if safety_data.get("is_emergency", False):
            context.is_emergency = True

    context.reasoning.append("Mission start workflow completed")
    return context
