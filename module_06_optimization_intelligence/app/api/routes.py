"""
API Routes and WebSocket Handler.

Defines REST and WebSocket endpoints for Module 06 Optimization Intelligence.
"""

from __future__ import annotations

import json
import uuid
import structlog
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends

from app.config.settings import Settings, get_settings
from app.models.optimization_request import OptimizationRequest, ScenarioType
from app.models.optimization_result import OptimizationResult
from app.agents.optimizer_agent import OptimizerAgent
from app.core.plan_validator import PlanValidator
from app.clients.module_clients import MockSubsystemClients
from app.api.schemas import (
    RunOptimizationHTTPResponse,
    ReplanHTTPRequest,
    ScenarioRunHTTPResponse,
    ValidationHTTPRequest,
    ValidationHTTPResponse,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

# Global memory cache for runs (persisted to DB as well)
_run_cache: Dict[str, OptimizationResult] = {}
_ws_connections: List[WebSocket] = []


def get_agent(settings: Settings = Depends(get_settings)) -> OptimizerAgent:
    """Dependency injector for Optimizer Agent."""
    return OptimizerAgent(settings)


@router.get("/health")
async def health_check():
    """Service health check endpoint."""
    return {
        "service": "Module 06 Optimization Intelligence",
        "status": "HEALTHY",
        "primary_solver": "Google OR-Tools",
        "secondary_solver": "Pyomo",
        "version": "1.0.0",
    }


@router.get("/optimization/status")
async def get_status(settings: Settings = Depends(get_settings)):
    """Module operational status."""
    return {
        "station_id": settings.station_id,
        "default_solver": settings.default_solver,
        "cached_runs_count": len(_run_cache),
        "max_solve_time_seconds": settings.max_solve_time_seconds,
        "lexicographic_mode": settings.enable_lexicographic_mode,
    }


@router.post("/optimization/run", response_model=RunOptimizationHTTPResponse)
async def run_optimization(
    request: Optional[OptimizationRequest] = None,
    agent: OptimizerAgent = Depends(get_agent)
):
    """
    POST /optimization/run
    Execute optimization for given request (or default mock request if none provided).
    """
    if request is None:
        request = OptimizationRequest(
            request_id=f"REQ-{uuid.uuid4().hex[:8].upper()}",
            missions=MockSubsystemClients.get_mock_missions(),
            energy_state=MockSubsystemClients.get_mock_energy_state(),
            forecast=MockSubsystemClients.get_mock_forecast(24, "BASELINE"),
            equipment=MockSubsystemClients.get_mock_equipment(),
            reserve=MockSubsystemClients.get_mock_reserve(),
        )

    eval_out = agent.evaluate_and_optimize(request, run_multi_scenarios=False)
    res: OptimizationResult = eval_out["result"]

    _run_cache[res.optimization_id] = res

    # Notify WebSocket listeners
    await broadcast_ws_message({"type": "OPTIMIZATION_COMPLETED", "result_id": res.optimization_id, "feasible": res.feasible})

    return RunOptimizationHTTPResponse(
        success=res.feasible,
        optimization_id=res.optimization_id,
        status=res.solver_status,
        result=res,
        explanation=eval_out["agent_explanation"],
    )


@router.post("/optimization/replan", response_model=RunOptimizationHTTPResponse)
async def replan_optimization(
    req: ReplanHTTPRequest,
    agent: OptimizerAgent = Depends(get_agent)
):
    """
    POST /optimization/replan
    Trigger rapid re-optimization upon subsystem events (generation drop, load spike, etc.).
    """
    logger.info("Re-optimization requested", trigger_event=req.trigger_event)
    opt_req = req.override_request

    if opt_req is None:
        opt_req = OptimizationRequest(
            request_id=f"REPLAN-{uuid.uuid4().hex[:8].upper()}",
            missions=MockSubsystemClients.get_mock_missions(),
            energy_state=MockSubsystemClients.get_mock_energy_state(),
            forecast=MockSubsystemClients.get_mock_forecast(24, "POLAR_NIGHT"),
            equipment=MockSubsystemClients.get_mock_equipment(),
            reserve=MockSubsystemClients.get_mock_reserve(),
        )

    eval_out = agent.evaluate_and_optimize(opt_req, run_multi_scenarios=False)
    res: OptimizationResult = eval_out["result"]
    _run_cache[res.optimization_id] = res

    return RunOptimizationHTTPResponse(
        success=res.feasible,
        optimization_id=res.optimization_id,
        status=res.solver_status,
        result=res,
        explanation=f"Re-optimization triggered by event '{req.trigger_event}'. {eval_out['agent_explanation']}",
    )


@router.post("/optimization/scenarios", response_model=ScenarioRunHTTPResponse)
async def run_scenarios(
    request: Optional[OptimizationRequest] = None,
    agent: OptimizerAgent = Depends(get_agent)
):
    """
    POST /optimization/scenarios
    Run multi-scenario optimization (BASELINE, LOW_RENEWABLE, HIGH_LOAD, WIND_COLLAPSE, STORM).
    """
    if request is None:
        request = OptimizationRequest(
            request_id=f"SCEN-REQ-{uuid.uuid4().hex[:8].upper()}",
            missions=MockSubsystemClients.get_mock_missions(),
            energy_state=MockSubsystemClients.get_mock_energy_state(),
            forecast=MockSubsystemClients.get_mock_forecast(24, "BASELINE"),
            equipment=MockSubsystemClients.get_mock_equipment(),
            reserve=MockSubsystemClients.get_mock_reserve(),
        )

    eval_out = agent.evaluate_and_optimize(request, run_multi_scenarios=True)
    sc_results = eval_out["scenario_results"]

    for sc_name, sc_res in sc_results.items():
        _run_cache[sc_res.optimization_id] = sc_res

    return ScenarioRunHTTPResponse(
        station_id=request.station_id,
        scenarios_evaluated=list(sc_results.keys()),
        results=sc_results,
        summary_explanation=eval_out["agent_explanation"],
    )


@router.get("/optimization/{optimization_id}")
async def get_optimization_run(optimization_id: str):
    """GET /optimization/{optimization_id}"""
    if optimization_id not in _run_cache:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    return _run_cache[optimization_id]


@router.get("/optimization/{optimization_id}/constraints")
async def get_run_constraints(optimization_id: str):
    """GET /optimization/{optimization_id}/constraints"""
    if optimization_id not in _run_cache:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    res = _run_cache[optimization_id]
    return {
        "optimization_id": res.optimization_id,
        "constraint_summary": res.constraint_summary,
        "violations": res.violations,
        "validation_passed": res.validation_passed,
    }


@router.get("/optimization/{optimization_id}/missions")
async def get_run_missions(optimization_id: str):
    """GET /optimization/{optimization_id}/missions"""
    if optimization_id not in _run_cache:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    res = _run_cache[optimization_id]
    return {
        "optimization_id": res.optimization_id,
        "mission_allocations": res.mission_allocations,
    }


@router.get("/optimization/{optimization_id}/storage")
async def get_run_storage(optimization_id: str):
    """GET /optimization/{optimization_id}/storage"""
    if optimization_id not in _run_cache:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    res = _run_cache[optimization_id]
    return {
        "optimization_id": res.optimization_id,
        "storage_schedule": res.storage_schedule,
    }


@router.get("/optimization/{optimization_id}/reserve")
async def get_run_reserve(optimization_id: str):
    """GET /optimization/{optimization_id}/reserve"""
    if optimization_id not in _run_cache:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    res = _run_cache[optimization_id]
    return {
        "optimization_id": res.optimization_id,
        "reserve_trajectory": res.reserve_trajectory,
    }


@router.get("/optimization/{optimization_id}/explanation")
async def get_run_explanation(optimization_id: str):
    """GET /optimization/{optimization_id}/explanation"""
    if optimization_id not in _run_cache:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    res = _run_cache[optimization_id]
    return {
        "optimization_id": res.optimization_id,
        "objective_breakdown": res.objective_breakdown,
        "explanations": res.explanations,
        "warnings": res.warnings,
        "infeasibility_report": res.infeasibility_report,
    }


@router.post("/optimization/validate", response_model=ValidationHTTPResponse)
async def validate_candidate_plan(payload: ValidationHTTPRequest):
    """
    POST /optimization/validate
    Independent deterministic validation check endpoint.
    """
    is_valid, violations = PlanValidator.validate_plan(payload.request, payload.var_values)
    return ValidationHTTPResponse(
        is_valid=is_valid,
        violation_count=len(violations),
        violations=[v.model_dump() for v in violations],
    )


@router.websocket("/optimization/stream")
async def websocket_stream(websocket: WebSocket):
    """WebSocket stream endpoint for real-time optimization status and events."""
    await websocket.accept()
    _ws_connections.append(websocket)
    logger.info("WebSocket client connected to /optimization/stream")
    try:
        while True:
            data = await websocket.receive_text()
            # Echo heartbeat or process message
            await websocket.send_text(json.dumps({"event": "PONG", "received": data}))
    except WebSocketDisconnect:
        _ws_connections.remove(websocket)
        logger.info("WebSocket client disconnected")


async def broadcast_ws_message(msg: Dict[str, Any]):
    """Broadcast JSON message to all active WebSocket clients."""
    for ws in list(_ws_connections):
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            _ws_connections.remove(ws)
