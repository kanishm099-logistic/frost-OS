"""
Frost OS Module 01 — Equipment Failure Workflow.

Handles EQUIPMENT_DEGRADED, TURBINE_ANOMALY, COMMUNICATION_LOSS.

Pipeline:
  Diagnostic + Energy + Forecast (parallel)
  → Optimizer
  → Reserve + Safety
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.models.event import StationEvent
from app.models.decision import DecisionContext, ModuleResponse

logger = structlog.get_logger(__name__)


async def equipment_failure_workflow(
    event: StationEvent,
    context: DecisionContext,
    clients: Any,
) -> DecisionContext:
    """Handle equipment failure/degradation events."""

    await logger.ainfo(
        "Starting equipment_failure workflow",
        event_id=event.event_id,
        event_type=event.event_type.value,
    )

    # ── Stage 1: Diagnostic-first + Energy + Forecast (parallel) ─────
    context.reasoning.append("Running diagnostics and gathering energy/forecast data")

    diag_task = asyncio.create_task(
        clients.diagnostic.diagnose_equipment(event.station_id, event)
    )
    energy_task = asyncio.create_task(
        clients.energy.get_energy_status(event.station_id)
    )
    forecast_task = asyncio.create_task(
        clients.forecast.get_forecast(event.station_id, hours=12)
    )

    results = await asyncio.gather(
        diag_task, energy_task, forecast_task,
        return_exceptions=True,
    )

    for name, result in [
        ("diagnostic", results[0]),
        ("energy", results[1]),
        ("forecast", results[2]),
    ]:
        if isinstance(result, Exception):
            context.degraded_modules.append(name)
            result = ModuleResponse(
                module_name=name, status="error",
                error_message=str(result), is_degraded=True, confidence=0.0,
            )
        if name == "diagnostic":
            context.diagnostic_analysis = result
        elif name == "energy":
            context.energy_analysis = result
        else:
            context.forecast_analysis = result
        if hasattr(result, "is_degraded") and result.is_degraded:
            if name not in context.degraded_modules:
                context.degraded_modules.append(name)

    if context.diagnostic_analysis and context.diagnostic_analysis.status == "success":
        diag = context.diagnostic_analysis.data.get("diagnostics", {})
        health = diag.get("overall_health_score", "?")
        context.reasoning.append(f"Equipment health score: {health}")
        issues = diag.get("issues", [])
        for issue in issues:
            context.reasoning.append(
                f"Issue: {issue.get('type', '?')} — {issue.get('description', '?')}"
            )

    # ── Stage 2: Optimizer ───────────────────────────────────────────
    context.reasoning.append("Optimizing with equipment constraints")

    optimizer_context = {
        "event": event.model_dump(mode="json"),
        "diagnostic": context.diagnostic_analysis.data if context.diagnostic_analysis else {},
        "energy": context.energy_analysis.data if context.energy_analysis else {},
        "forecast": context.forecast_analysis.data if context.forecast_analysis else {},
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
            context.reasoning.append("EMERGENCY: Equipment failure requires immediate action")

    context.reasoning.append("Equipment failure workflow completed")
    return context
