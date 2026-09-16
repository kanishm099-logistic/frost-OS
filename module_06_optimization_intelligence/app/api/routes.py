"""
API Routes and WebSocket Handler.

Defines REST and WebSocket endpoints for Module 06 Optimization Intelligence.
"""

from __future__ import annotations

import json
import uuid
import structlog
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query, Request

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
    M01ModuleResponse,
    M01OptimizeResponseData,
    M01OptimizationResult,
    ActionItem,
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


@router.get("/optimization/priority-dispatch", tags=["Priority Process"])
@router.post("/optimization/priority-dispatch", tags=["Priority Process"])
async def priority_dispatch(
    request: Request,
    deficit_kw: float = Query(default=0.0),
    station_id: str = Query(default="FROST-STATION-ALPHA"),
):
    """
    Compute priority-based load shedding and process dispatch under generation deficits.
    Executes lexicographic priority ordering:
    P3 Comfort is shed first (0-20 kW),
    P2 Deferred Experiments is shed second (20-55 kW),
    P1 Essential Science is protected/buffered (55+ kW),
    P0 Life Support is strictly protected (never shed).
    """
    if request.method == "POST":
        try:
            body = await request.json()
            if isinstance(body, dict):
                if "deficit_kw" in body:
                    deficit_kw = float(body["deficit_kw"])
                if "station_id" in body:
                    station_id = str(body["station_id"])
        except Exception:
            pass
    deficit_kw = max(0.0, float(deficit_kw))

    # Nominal allocations
    p0_nom = 45.0
    p1_nom = 90.0
    p2_nom = 35.0
    p3_nom = 20.0
    total_nom = p0_nom + p1_nom + p2_nom + p3_nom

    # Cascading shedding
    # Step 1: Shed P3 (up to 20 kW)
    p3_shed = min(deficit_kw, p3_nom)
    p3_alloc = p3_nom - p3_shed
    rem_deficit = deficit_kw - p3_shed

    # Step 2: Shed P2 (up to 35 kW)
    p2_shed = min(rem_deficit, p2_nom)
    p2_alloc = p2_nom - p2_shed
    rem_deficit = rem_deficit - p2_shed

    # Step 3: P1 Essential Science & Battery Buffer (rem_deficit > 0)
    battery_dispatch_kw = 0.0
    p1_shed = 0.0
    if rem_deficit > 0:
        battery_dispatch_kw = min(200.0, rem_deficit)
        p1_unmet = rem_deficit - battery_dispatch_kw
        p1_shed = min(p1_unmet, p1_nom - 40.0)
    p1_alloc = p1_nom - p1_shed

    # P0 Life Support is NEVER shed
    p0_shed = 0.0
    p0_alloc = p0_nom

    total_delivered = p0_alloc + p1_alloc + p2_alloc + p3_alloc
    total_shed = p0_shed + p1_shed + p2_shed + p3_shed

    processes = [
        {
            "process_id": "PROC-P0-LIFE-SUPPORT",
            "name": "Life Support & Environmental Habitat",
            "tier": "P0",
            "priority": 0,
            "nominal_kw": p0_nom,
            "allocated_kw": round(p0_alloc, 1),
            "shed_kw": round(p0_shed, 1),
            "status": "PROTECTED (100%)",
            "badge_color": "emerald",
            "can_shed": False,
        },
        {
            "process_id": "PROC-P1-ESSENTIAL-SCIENCE",
            "name": "Atmospheric Radar & Ice Core Sampler",
            "tier": "P1",
            "priority": 1,
            "nominal_kw": p1_nom,
            "allocated_kw": round(p1_alloc, 1),
            "shed_kw": round(p1_shed, 1),
            "status": "ACTIVE" if p1_shed == 0 else "BUFFERED / THROTTLED",
            "badge_color": "cyan",
            "can_shed": False,
        },
        {
            "process_id": "PROC-P2-DEFERRED-RESEARCH",
            "name": "Secondary Thermal Sensors & Drone Charging",
            "tier": "P2",
            "priority": 2,
            "nominal_kw": p2_nom,
            "allocated_kw": round(p2_alloc, 1),
            "shed_kw": round(p2_shed, 1),
            "status": "ACTIVE" if p2_shed == 0 else ("SHED" if p2_alloc == 0 else "THROTTLED"),
            "badge_color": "amber" if p2_shed > 0 else "blue",
            "can_shed": True,
        },
        {
            "process_id": "PROC-P3-STATION-COMFORT",
            "name": "Quarters Comfort HVAC & Auxiliary Amenities",
            "tier": "P3",
            "priority": 3,
            "nominal_kw": p3_nom,
            "allocated_kw": round(p3_alloc, 1),
            "shed_kw": round(p3_shed, 1),
            "status": "ACTIVE" if p3_shed == 0 else ("SHED" if p3_alloc == 0 else "THROTTLED"),
            "badge_color": "rose" if p3_shed > 0 else "slate",
            "can_shed": True,
        },
    ]

    actions = []
    if p3_shed > 0:
        actions.append({
            "action_id": f"ACT-PRIORITY-SHED-P3-{int(deficit_kw)}",
            "priority": 0,
            "action_type": "REDUCE_LOAD",
            "target": "P3-COMFORT",
            "power_kw": round(p3_shed, 1),
            "rationale": f"Tier 1 priority shed: cut non-essential comfort load (-{p3_shed:.1f} kW) to balance deficit",
        })
    if p2_shed > 0:
        actions.append({
            "action_id": f"ACT-PRIORITY-SHED-P2-{int(deficit_kw)}",
            "priority": 1,
            "action_type": "PAUSE_MISSION",
            "target": "P2-EXPERIMENTS",
            "power_kw": round(p2_shed, 1),
            "rationale": f"Tier 2 priority shed: pause deferred experiments (-{p2_shed:.1f} kW) to protect station reserve",
        })
    if battery_dispatch_kw > 0:
        actions.append({
            "action_id": f"ACT-PRIORITY-BATT-DIS-{int(deficit_kw)}",
            "priority": 2,
            "action_type": "DISCHARGE_BATTERY",
            "target": "BAT-01",
            "power_kw": round(battery_dispatch_kw, 1),
            "rationale": f"Tier 3 priority safeguard: discharge battery (+{battery_dispatch_kw:.1f} kW) to guard P1 Science & P0 Life Support",
        })

    return {
        "station_id": station_id,
        "deficit_kw": deficit_kw,
        "nominal_demand_kw": total_nom,
        "allocated_power_kw": round(total_delivered, 1),
        "total_shed_kw": round(total_shed, 1),
        "battery_support_kw": round(battery_dispatch_kw, 1),
        "solver_strategy": "LEXICOGRAPHIC_PRIORITY_CASCADE",
        "safety_audit": "PASSED — P0 LIFE SUPPORT 100% PROTECTED",
        "p0_violation": False,
        "processes": processes,
        "actions": actions,
    }


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


# ── Module 01 Orchestrator Inter-Module Contract Compatibility Routes ──

@router.post("/optimizer/station/{station_id}/optimize", response_model=M01ModuleResponse)
@router.post("/optimization/station/{station_id}/optimize", response_model=M01ModuleResponse)
async def optimize_station_m01_compat(
    station_id: str,
    context: Optional[Dict[str, Any]] = None,
    agent: OptimizerAgent = Depends(get_agent),
) -> M01ModuleResponse:
    """
    Backward-compatible REST contract for Module 01 Orchestrator OptimizerClient.
    Receives station context (events, generation drops, load, storage reserves)
    and returns structured optimization decision actions in standard ModuleResponse format.
    """
    if context is None:
        context = {}

    req = OptimizationRequest(
        request_id=f"M01-{uuid.uuid4().hex[:8].upper()}",
        station_id=station_id,
        missions=MockSubsystemClients.get_mock_missions(),
        energy_state=MockSubsystemClients.get_mock_energy_state(),
        forecast=MockSubsystemClients.get_mock_forecast(24, "BASELINE"),
        equipment=MockSubsystemClients.get_mock_equipment(),
        reserve=MockSubsystemClients.get_mock_reserve(),
    )

    eval_out = agent.evaluate_and_optimize(req, run_multi_scenarios=False)
    res: OptimizationResult = eval_out["result"]
    _run_cache[res.optimization_id] = res

    # Build actionable recommendations list based on optimization dispatch results
    actions: List[ActionItem] = []

    # 1. Load curtailment / shedding actions from mission allocations
    for m_alloc in res.mission_allocations:
        if not m_alloc.satisfied:
            actions.append(
                ActionItem(
                    action_type="REDUCE_LOAD",
                    target=f"{m_alloc.mission_name} ({m_alloc.priority})",
                    description=f"Curtailed {m_alloc.mission_name} workload (allocated {m_alloc.allocated_power_kw} kW)",
                    parameters={
                        "allocated_power_kw": m_alloc.allocated_power_kw,
                        "priority": m_alloc.priority,
                    },
                    priority=1 if m_alloc.priority in ("P3", "P4") else 2,
                    estimated_impact_kwh=round(m_alloc.allocated_power_kw * 1.0, 2),
                    reversible=True,
                )
            )

    # 2. Storage activation actions
    if res.storage_schedule:
        avg_discharge = sum(s.battery_discharge_kw for s in res.storage_schedule) / max(1, len(res.storage_schedule))
        if avg_discharge > 0.1:
            actions.append(
                ActionItem(
                    action_type="ACTIVATE_STORAGE",
                    target="Battery Storage System",
                    description=f"Draw {round(avg_discharge, 1)} kW from battery storage to balance microgrid deficit",
                    parameters={
                        "discharge_rate_kw": round(avg_discharge, 1),
                        "estimated_duration_hours": len(res.storage_schedule),
                    },
                    priority=2,
                    estimated_impact_kwh=round(avg_discharge * len(res.storage_schedule), 2),
                    reversible=True,
                )
            )

    # Default fallback action if microgrid is fully balanced
    if not actions:
        actions.append(
            ActionItem(
                action_type="MAINTAIN_BALANCED_DISPATCH",
                target="Microgrid Controller",
                description="Optimal energy allocation active; generation satisfies all station demand",
                parameters={"status": "optimal"},
                priority=1,
                estimated_impact_kwh=0.0,
                reversible=True,
            )
        )

    # Compute projected reserve and confidence
    proj_reserve = res.reserve_trajectory[-1].projected_stored_energy_kwh if res.reserve_trajectory else 400.0
    confidence_val = 0.85 if res.feasible else 0.50

    return M01ModuleResponse(
        status="success",
        module_name="optimizer",
        data=M01OptimizeResponseData(
            station_id=station_id,
            optimization_result=M01OptimizationResult(
                strategy="load_shedding_with_storage" if any(a.action_type == "REDUCE_LOAD" for a in actions) else "optimal_dispatch",
                actions=actions,
                projected_balance_kw=0.0,
                projected_reserve_kwh=round(proj_reserve, 1),
                confidence=confidence_val,
            ),
        ),
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
