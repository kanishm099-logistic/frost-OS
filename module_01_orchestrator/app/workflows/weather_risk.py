"""
Frost OS Module 01 — Weather Risk Workflow.

Handles WEATHER_WARNING events.
Forecast-driven preemptive planning.

Pipeline:
  Forecast + Energy + Mission (parallel)
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


async def weather_risk_workflow(
    event: StationEvent,
    context: DecisionContext,
    clients: Any,
) -> DecisionContext:
    """Handle weather warning events with preemptive planning."""

    await logger.ainfo(
        "Starting weather_risk workflow",
        event_id=event.event_id,
        event_type=event.event_type.value,
    )

    # ── Stage 1: Forecast (primary) + Energy + Mission (parallel) ────
    context.reasoning.append("Analyzing weather forecast and current station state")

    forecast_task = asyncio.create_task(
        clients.forecast.get_weather_forecast(event.station_id)
    )
    energy_task = asyncio.create_task(
        clients.energy.get_energy_status(event.station_id)
    )
    mission_task = asyncio.create_task(
        clients.mission.get_active_missions(event.station_id)
    )

    results = await asyncio.gather(
        forecast_task, energy_task, mission_task,
        return_exceptions=True,
    )

    for name, result in [
        ("forecast", results[0]),
        ("energy", results[1]),
        ("mission", results[2]),
    ]:
        if isinstance(result, Exception):
            context.degraded_modules.append(name)
            result = ModuleResponse(
                module_name=name, status="error",
                error_message=str(result), is_degraded=True, confidence=0.0,
            )
        if name == "forecast":
            context.forecast_analysis = result
        elif name == "energy":
            context.energy_analysis = result
        else:
            context.mission_analysis = result
        if hasattr(result, "is_degraded") and result.is_degraded:
            if name not in context.degraded_modules:
                context.degraded_modules.append(name)

    if context.forecast_analysis and context.forecast_analysis.status == "success":
        weather = context.forecast_analysis.data
        icing = weather.get("icing_risk", "unknown")
        storm = weather.get("storm_warning", False)
        context.reasoning.append(f"Weather: icing_risk={icing}, storm_warning={storm}")
        if storm:
            context.reasoning.append("STORM WARNING: Preemptive protection measures needed")

    # ── Stage 2: Optimizer ───────────────────────────────────────────
    context.reasoning.append("Requesting preemptive weather-risk optimization")

    optimizer_context = {
        "event": event.model_dump(mode="json"),
        "forecast": context.forecast_analysis.data if context.forecast_analysis else {},
        "energy": context.energy_analysis.data if context.energy_analysis else {},
        "mission": context.mission_analysis.data if context.mission_analysis else {},
        "degraded_modules": context.degraded_modules,
        "priority": "weather_protection",
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
            context.reasoning.append("EMERGENCY: Severe weather requires immediate protective action")

    context.reasoning.append("Weather risk workflow completed")
    return context
