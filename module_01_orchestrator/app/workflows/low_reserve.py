"""
Frost OS Module 01 — Low Reserve Workflow.

Handles BATTERY_LOW and HYDROGEN_LOW events.
Reserve-critical workflow with potential emergency bypass.

Pipeline:
  Energy + Reserve + Mission (parallel)
  → Optimizer
  → Safety (critical — may flag emergency)
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.models.event import StationEvent
from app.models.decision import DecisionContext, ModuleResponse

logger = structlog.get_logger(__name__)


async def low_reserve_workflow(
    event: StationEvent,
    context: DecisionContext,
    clients: Any,
) -> DecisionContext:
    """Handle low reserve events (battery/hydrogen)."""

    await logger.ainfo(
        "Starting low_reserve workflow",
        event_id=event.event_id,
        event_type=event.event_type.value,
    )

    # ── Stage 1: Energy + Reserve status + Mission (parallel) ────────
    context.reasoning.append("Assessing current energy state and reserve levels")

    energy_task = asyncio.create_task(
        clients.energy.get_energy_status(event.station_id)
    )
    reserve_task = asyncio.create_task(
        clients.reserve.validate_reserves(event.station_id, {
            "event_type": event.event_type.value,
            "payload": event.payload,
        })
    )
    mission_task = asyncio.create_task(
        clients.mission.get_active_missions(event.station_id)
    )

    results = await asyncio.gather(
        energy_task, reserve_task, mission_task,
        return_exceptions=True,
    )

    for name, result in [
        ("energy", results[0]),
        ("reserve", results[1]),
        ("mission", results[2]),
    ]:
        if isinstance(result, Exception):
            context.degraded_modules.append(name)
            result = ModuleResponse(
                module_name=name, status="error",
                error_message=str(result), is_degraded=True, confidence=0.0,
            )
        if name == "energy":
            context.energy_analysis = result
        elif name == "reserve":
            context.reserve_validation = result
        else:
            context.mission_analysis = result
        if hasattr(result, "is_degraded") and result.is_degraded:
            if name not in context.degraded_modules:
                context.degraded_modules.append(name)

    # Check if reserve status already indicates emergency
    if context.reserve_validation and context.reserve_validation.status == "success":
        reserve_data = context.reserve_validation.data.get("reserve_validation", {})
        margin_pct = reserve_data.get("reserve_margin_pct", 100)
        context.reasoning.append(f"Reserve margin: {margin_pct:.1f}%")
        if margin_pct < 20:
            context.reasoning.append("CRITICAL: Reserve margin below 20%")

    # ── Stage 2: Optimizer ───────────────────────────────────────────
    context.reasoning.append("Requesting emergency-aware optimization")

    optimizer_context = {
        "event": event.model_dump(mode="json"),
        "energy": context.energy_analysis.data if context.energy_analysis else {},
        "reserve": context.reserve_validation.data if context.reserve_validation else {},
        "mission": context.mission_analysis.data if context.mission_analysis else {},
        "degraded_modules": context.degraded_modules,
        "priority": "reserve_protection",
    }
    context.optimization_result = await clients.optimizer.optimize_allocation(
        event.station_id, optimizer_context
    )
    if context.optimization_result.is_degraded:
        context.degraded_modules.append("optimizer")

    # ── Stage 3: Safety check (critical for low-reserve events) ──────
    context.reasoning.append("Safety validation for reserve-critical scenario")

    plan_data = {
        "optimization": context.optimization_result.data if context.optimization_result else {},
        "event_type": event.event_type.value,
        "reserve_status": context.reserve_validation.data if context.reserve_validation else {},
    }
    context.safety_validation = await clients.reserve.check_safety(
        event.station_id, plan_data
    )

    if context.safety_validation and context.safety_validation.status == "success":
        safety_data = context.safety_validation.data.get("safety_check", {})
        if safety_data.get("is_emergency", False):
            context.is_emergency = True
            context.reasoning.append(
                "EMERGENCY: M07 flagged low-reserve as emergency — immediate action authorized"
            )

    context.reasoning.append("Low reserve workflow completed")
    return context
