"""
Frost OS Module 01 — Generation Drop Workflow.

Handles WIND_POWER_DROP, SOLAR_OUTPUT_DROP, and LOAD_SPIKE events.

Pipeline:
  Energy + Forecast + Diagnostic + Mission (parallel)
  → Optimizer (sequential, depends on above)
  → Reserve (sequential, depends on optimizer)
  → Safety validation
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from app.models.event import StationEvent
from app.models.decision import DecisionContext

logger = structlog.get_logger(__name__)


async def generation_drop_workflow(
    event: StationEvent,
    context: DecisionContext,
    clients: Any,
) -> DecisionContext:
    """
    Handle generation drop events.

    Stage 1 (parallel): Energy + Forecast + Diagnostic + Mission
    Stage 2 (sequential): Optimizer (needs stage 1 results)
    Stage 3 (sequential): Reserve validation (needs optimizer result)
    Stage 4 (sequential): Safety check
    """
    await logger.ainfo(
        "Starting generation_drop workflow",
        event_id=event.event_id,
        event_type=event.event_type.value,
    )

    # ── Stage 1: Parallel module queries ──────────────────────────────
    context.reasoning.append("Gathering energy, forecast, diagnostic, and mission data in parallel")

    energy_task = asyncio.create_task(
        clients.energy.analyze_generation_event(event.station_id, event)
    )
    forecast_task = asyncio.create_task(
        clients.forecast.get_forecast(event.station_id, hours=24)
    )
    diagnostic_task = asyncio.create_task(
        clients.diagnostic.diagnose_equipment(event.station_id, event)
    )
    mission_task = asyncio.create_task(
        clients.mission.get_active_missions(event.station_id)
    )

    results = await asyncio.gather(
        energy_task, forecast_task, diagnostic_task, mission_task,
        return_exceptions=True,
    )

    # Unpack results, handling exceptions
    for i, (name, result) in enumerate([
        ("energy", results[0]),
        ("forecast", results[1]),
        ("diagnostic", results[2]),
        ("mission", results[3]),
    ]):
        if isinstance(result, Exception):
            await logger.aerror(f"Module {name} failed", error=str(result))
            context.degraded_modules.append(name)
            from app.models.decision import ModuleResponse
            result = ModuleResponse(
                module_name=name,
                status="error",
                error_message=str(result),
                is_degraded=True,
                confidence=0.0,
            )

        if name == "energy":
            context.energy_analysis = result
        elif name == "forecast":
            context.forecast_analysis = result
        elif name == "diagnostic":
            context.diagnostic_analysis = result
        elif name == "mission":
            context.mission_analysis = result

        if hasattr(result, "is_degraded") and result.is_degraded:
            if name not in context.degraded_modules:
                context.degraded_modules.append(name)

    # Build reasoning from stage 1
    if context.energy_analysis and context.energy_analysis.status == "success":
        analysis = context.energy_analysis.data.get("analysis", {})
        drop_pct = analysis.get("drop_pct", 0)
        context.reasoning.append(
            f"Energy analysis: {drop_pct:.1f}% generation drop detected"
        )

    if context.forecast_analysis and context.forecast_analysis.status == "success":
        trend = context.forecast_analysis.data.get("trend", "unknown")
        context.reasoning.append(f"Forecast trend: {trend}")

    if context.diagnostic_analysis and context.diagnostic_analysis.status == "success":
        diag = context.diagnostic_analysis.data.get("diagnostics", {})
        issues = diag.get("issues", [])
        if issues:
            context.reasoning.append(
                f"Diagnostic issues: {', '.join(i.get('type', '?') for i in issues)}"
            )

    # ── Stage 2: Optimizer (depends on stage 1) ──────────────────────
    context.reasoning.append("Requesting optimization based on gathered analysis")

    optimizer_context = {
        "event": event.model_dump(mode="json"),
        "energy": context.energy_analysis.data if context.energy_analysis else {},
        "forecast": context.forecast_analysis.data if context.forecast_analysis else {},
        "diagnostic": context.diagnostic_analysis.data if context.diagnostic_analysis else {},
        "mission": context.mission_analysis.data if context.mission_analysis else {},
        "degraded_modules": context.degraded_modules,
    }

    context.optimization_result = await clients.optimizer.optimize_allocation(
        event.station_id, optimizer_context
    )

    if context.optimization_result.is_degraded:
        context.degraded_modules.append("optimizer")
        context.reasoning.append("WARNING: Optimizer unavailable — plan may be suboptimal")

    # ── Stage 3: Reserve validation (depends on optimizer) ───────────
    context.reasoning.append("Validating reserves against proposed plan")

    plan_data = {
        "optimization": context.optimization_result.data if context.optimization_result else {},
        "event_type": event.event_type.value,
        "severity": event.severity.value,
    }
    context.reserve_validation = await clients.reserve.validate_reserves(
        event.station_id, plan_data
    )

    if context.reserve_validation.is_degraded:
        context.degraded_modules.append("reserve")

    # ── Stage 4: Safety check ────────────────────────────────────────
    context.reasoning.append("Performing safety validation")

    context.safety_validation = await clients.reserve.check_safety(
        event.station_id, plan_data
    )

    if context.safety_validation and context.safety_validation.status == "success":
        safety_data = context.safety_validation.data.get("safety_check", {})
        if safety_data.get("is_emergency", False):
            context.is_emergency = True
            context.reasoning.append("EMERGENCY: M07 flagged this as emergency — bypassing authorization")

    await logger.ainfo(
        "Generation drop workflow completed",
        event_id=event.event_id,
        degraded_modules=context.degraded_modules,
        is_emergency=context.is_emergency,
    )

    return context
