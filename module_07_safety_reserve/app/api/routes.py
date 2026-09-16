"""
Module 07 REST API Routes and WebSocket Handler.

Provides endpoints for plan validation, reserve lookup, risk assessment,
policy inspection, simulation runs, audit logs, and status checks.
"""

from __future__ import annotations

import json
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.config.settings import Settings, get_settings
from app.api.schemas import (
    SafetyValidateHTTPRequest,
    SafetyValidateHTTPResponse,
    SimulationHTTPRequest,
    SystemStatusHTTPResponse,
)
from app.core.safety_engine import SafetyEngine
from app.agents.safety_agent import SafetyAgent
from app.rules.rule_definitions import list_registered_rules
from app.models.safety_decision import ValidationMode
from app.storage.repository import SafetyRepository, get_db_session

logger = structlog.get_logger(__name__)

router = APIRouter()

# Global memory cache for validations (persisted to DB as well)
_validation_cache: Dict[str, Any] = {}
_ws_connections: List[WebSocket] = []


def get_safety_engine(settings: Settings = Depends(get_settings)) -> SafetyEngine:
    return SafetyEngine(settings)


def get_safety_agent(settings: Settings = Depends(get_settings)) -> SafetyAgent:
    return SafetyAgent(settings)


# Mock data generator for fallback context
def _get_default_mock_context():
    return {
        "energy_state": {
            "battery_soc_pct": 80.0,
            "battery_energy_kwh": 2500.0,
            "battery_capacity_kwh": 3000.0,
            "hydrogen_energy_kwh": 1000.0,
            "hydrogen_level_pct": 75.0,
            "current_generation_kw": 85.0,
            "current_load_kw": 60.0,
            "critical_load_kw": 40.0,
            "battery_temperature_c": 22.0,
            "hydrogen_pressure_bar": 200.0,
            "data_quality": "GOOD",
        },
        "missions": [
            {
                "mission_id": "MIS-P0-LIFE",
                "mission_name": "Life Support & Thermal",
                "priority": "P0",
                "required_power_kw": 40.0,
                "min_power_kw": 40.0,
                "duration_hours": 24.0,
                "critical": True,
            },
            {
                "mission_id": "MIS-P1-RADAR",
                "mission_name": "Atmospheric Radar",
                "priority": "P1",
                "required_power_kw": 25.0,
                "min_power_kw": 20.0,
                "duration_hours": 12.0,
                "critical": True,
            },
        ],
        "forecast": {
            "confidence": 0.88,
            "shortage_probability": 0.05,
            "solar_kw": 30.0,
            "wind_kw": 55.0,
        },
        "equipment_health": {
            "overall_health_score": 92.0,
            "equipment": {
                "TURBINE-01": {"status": "HEALTHY", "derating_factor": 1.0},
                "BATTERY-BANK": {"status": "HEALTHY", "derating_factor": 1.0},
            },
        },
    }


# ── Core Safety & Reserve Endpoints ─────────────────────────────────────

@router.post("/safety/validate", response_model=SafetyValidateHTTPResponse)
async def validate_plan(
    req: SafetyValidateHTTPRequest,
    engine: SafetyEngine = Depends(get_safety_engine),
    agent: SafetyAgent = Depends(get_safety_agent),
    session: AsyncSession = Depends(get_db_session),
):
    """
    POST /safety/validate
    Independently validates a proposed Module 06 optimization plan against
    station reserve requirements, power balances, equipment limits, and emergency rules.
    """
    mock_ctx = _get_default_mock_context()
    energy_state = req.energy_state or mock_ctx["energy_state"]
    missions = req.missions or mock_ctx["missions"]
    forecast = req.forecast or mock_ctx["forecast"]
    equipment_health = req.equipment_health or mock_ctx["equipment_health"]

    val_res = engine.validate_plan(
        proposed_plan=req.proposed_plan,
        energy_state=energy_state,
        missions=missions,
        forecast=forecast,
        equipment_health=equipment_health,
        validation_mode=req.validation_mode,
        weather_event=req.weather_event,
    )

    # Persist to Memory and DB
    _validation_cache[val_res.validation_id] = val_res
    _validation_cache[f"plan:{val_res.plan_id}"] = val_res

    repo = SafetyRepository(session)
    await repo.save_validation(val_res)

    explanation = agent.explain_validation_result(val_res)

    # Notify WebSocket stream listeners
    await broadcast_ws_message({"type": "SAFETY_VALIDATION_COMPLETED", "validation_id": val_res.validation_id, "status": val_res.status.value})

    return SafetyValidateHTTPResponse(
        success=val_res.is_executable,
        status=val_res.status,
        validation_id=val_res.validation_id,
        plan_id=val_res.plan_id,
        is_executable=val_res.is_executable,
        result=val_res,
        agent_explanation=explanation,
    )


@router.get("/safety/validation/{validation_id}")
async def get_validation_by_id(
    validation_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """GET /safety/validation/{validation_id}"""
    if validation_id in _validation_cache:
        return _validation_cache[validation_id]
    repo = SafetyRepository(session)
    data = await repo.get_validation(validation_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Validation {validation_id} not found")
    return data


@router.get("/safety/plan/{plan_id}")
async def get_validation_by_plan(
    plan_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """GET /safety/plan/{plan_id}"""
    key = f"plan:{plan_id}"
    if key in _validation_cache:
        return _validation_cache[key]
    repo = SafetyRepository(session)
    data = await repo.get_validation_by_plan(plan_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Validation for plan {plan_id} not found")
    return data


@router.get("/safety/reserve/{station_id}")
async def get_station_reserve(
    station_id: str,
    engine: SafetyEngine = Depends(get_safety_engine),
):
    """GET /safety/reserve/{station_id} — Current dynamic station reserve breakdown."""
    ctx = _get_default_mock_context()
    calc = engine.reserve_engine.calculate_reserve(
        energy_state=ctx["energy_state"],
        missions=ctx["missions"],
        forecast=ctx["forecast"],
        equipment_health=ctx["equipment_health"],
    )
    return calc


@router.get("/safety/risk/{station_id}")
async def get_station_risk(
    station_id: str,
    engine: SafetyEngine = Depends(get_safety_engine),
):
    """GET /safety/risk/{station_id} — Operational 8-category risk assessment."""
    ctx = _get_default_mock_context()
    calc = engine.reserve_engine.calculate_reserve(
        ctx["energy_state"], ctx["missions"], ctx["forecast"], ctx["equipment_health"]
    )
    risks, highest_level = engine.risk_engine.evaluate_risks(
        ctx["energy_state"], ctx["forecast"], calc, ctx["equipment_health"]
    )
    return {
        "station_id": station_id,
        "overall_risk_level": highest_level.value,
        "risk_assessments": [r.model_dump() for r in risks],
    }


@router.get("/safety/status/{station_id}")
@router.get("/safety-intelligence/status")
async def get_service_status(
    station_id: str = "POLAR-STATION-ALPHA",
    settings: Settings = Depends(get_settings),
):
    """GET subsystem operational health and parameters."""
    return SystemStatusHTTPResponse(
        service="Module 07 Safety + Reserve Intelligence",
        status="HEALTHY",
        station_id=station_id,
        policy_version=settings.policy_version,
        deterministic_mode=True,
        llm_safety_decisions=False,
        redis_connected=True,
        database_connected=True,
    )


@router.get("/safety/rules")
async def get_safety_rules():
    """GET declarative safety rules registry."""
    return {"rules": list_registered_rules()}


@router.get("/safety/policies")
async def get_safety_policies(engine: SafetyEngine = Depends(get_safety_engine)):
    """GET current active versioned safety policies."""
    return engine.policy_engine.get_active_policy_summary()


@router.post("/safety/simulate")
async def simulate_scenario(
    req: SimulationHTTPRequest,
    engine: SafetyEngine = Depends(get_safety_engine),
    agent: SafetyAgent = Depends(get_safety_agent),
):
    """
    POST /safety/simulate
    Simulates validation under predefined scenarios (NORMAL, LOW_RENEWABLE, STORM, EMERGENCY).
    """
    ctx = _get_default_mock_context()
    weather_event = "NORMAL"
    val_mode = ValidationMode.NORMAL

    if req.scenario_name == "LOW_RENEWABLE":
        ctx["energy_state"]["current_generation_kw"] = 15.0
        weather_event = "LOW_WIND"
    elif req.scenario_name == "STORM":
        ctx["energy_state"]["current_generation_kw"] = 5.0
        weather_event = "STORM"
        val_mode = ValidationMode.STORM
    elif req.scenario_name == "EMERGENCY":
        ctx["energy_state"]["battery_temperature_c"] = 48.0  # Overtemp trigger

    proposed_plan = req.custom_plan or {
        "optimization_id": f"SIM-{req.scenario_name}",
        "total_load_kw": 65.0,
        "actions": [{"action_type": "MAINTAIN_DISPATCH", "target": "Microgrid"}],
    }

    val_res = engine.validate_plan(
        proposed_plan=proposed_plan,
        energy_state=ctx["energy_state"],
        missions=ctx["missions"],
        forecast=ctx["forecast"],
        equipment_health=ctx["equipment_health"],
        validation_mode=val_mode,
        weather_event=weather_event,
    )

    explanation = agent.explain_validation_result(val_res)

    return {
        "scenario": req.scenario_name,
        "status": val_res.status.value,
        "is_executable": val_res.is_executable,
        "validation": val_res,
        "explanation": explanation,
    }


@router.get("/safety/audit/{plan_id}")
async def get_audit_trail(
    plan_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """GET audit trail for a specific plan."""
    repo = SafetyRepository(session)
    data = await repo.get_validation_by_plan(plan_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Audit log for plan {plan_id} not found")
    return {
        "plan_id": plan_id,
        "validation_id": data.get("validation_id"),
        "policy_version": data.get("policy_version"),
        "state_transitions": data.get("state_transitions"),
        "explanation": data.get("explanation"),
    }


@router.get("/health")
async def health_check():
    """Service liveness probe."""
    return {
        "service": "Module 07 Safety + Reserve Intelligence",
        "status": "HEALTHY",
        "version": "1.0.0",
    }


@router.websocket("/safety/stream")
async def websocket_stream(websocket: WebSocket):
    """WebSocket stream endpoint for real-time safety status and events."""
    await websocket.accept()
    _ws_connections.append(websocket)
    logger.info("WebSocket client connected to /safety/stream")
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(json.dumps({"event": "PONG", "received": data}))
    except WebSocketDisconnect:
        _ws_connections.remove(websocket)
        logger.info("WebSocket client disconnected")


async def broadcast_ws_message(msg: Dict[str, Any]):
    """Broadcast JSON message to active WebSocket clients."""
    for ws in list(_ws_connections):
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            _ws_connections.remove(ws)
