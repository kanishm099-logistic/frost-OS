"""
Frost OS Module 03 — REST API Routes.

Exposes REST endpoints for telemetry ingestion, state snapshots, storage analysis,
operational alerts, agent interactions, and Module 01 Orchestrator compatibility.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.agents.energy_agent import EnergyAgent
from app.api.schemas import (
    AgentQueryRequest,
    AgentQueryResponse,
    LoadEvaluationRequest,
    LoadEvaluationResponse,
    M01AnalyzeResponse,
    M01EnergyStatusResponse,
    SimulateRequest,
    TelemetryBatchRequest,
    TelemetryIngestResponse,
)
from app.core.energy_engine import EnergyEngine
from app.models.energy_state import EnergyState, EnergyStatus
from app.models.storage import BatteryState, HydrogenState, ThermalStorageState
from app.models.telemetry import TelemetryRecord
from app.storage.database import get_session_dependency
from app.storage.repository import (
    AlertRepository,
    EnergyStateRepository,
    TelemetryRepository,
)
from app.telemetry.simulator import PolarStationSimulator

logger = structlog.get_logger(__name__)
router = APIRouter()

# Global engine and agent references (injected from app.main on startup)
_engine: EnergyEngine | None = None
_agent: EnergyAgent | None = None
_simulator_map: dict[str, PolarStationSimulator] = {}


def set_engine_and_agent(engine: EnergyEngine, agent: EnergyAgent) -> None:
    """Set the module-level engine and agent singletons."""
    global _engine, _agent
    _engine = engine
    _agent = agent


def get_engine() -> EnergyEngine:
    """Retrieve initialized EnergyEngine instance."""
    if _engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="EnergyEngine has not been initialized",
        )
    return _engine


def get_agent() -> EnergyAgent:
    """Retrieve initialized EnergyAgent instance."""
    if _agent is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="EnergyAgent has not been initialized",
        )
    return _agent


# ── Telemetry Ingestion ───────────────────────────────────────────────

@router.post(
    "/api/v1/telemetry",
    response_model=TelemetryIngestResponse,
    status_code=status.HTTP_200_OK,
)
async def ingest_telemetry_batch(
    payload: TelemetryBatchRequest,
    session: AsyncSession = Depends(get_session_dependency),
    engine: EnergyEngine = Depends(get_engine),
):
    """Ingest a batch of telemetry records, update state, and persist."""
    records = payload.records
    station_id = records[0].station_id

    # Persist raw telemetry
    telemetry_repo = TelemetryRepository(session)
    await telemetry_repo.save_batch(records)

    # Process through 13-step energy pipeline
    state, alerts = await engine.process_telemetry(records)

    # Persist state snapshot and alerts
    state_repo = EnergyStateRepository(session)
    await state_repo.save(state)

    if alerts:
        alert_repo = AlertRepository(session)
        await alert_repo.save_batch(alerts)

    return TelemetryIngestResponse(
        processed_count=len(records),
        rejected_count=0,
        station_id=station_id,
        energy_state=state,
        alerts_triggered=state.active_alerts,
    )


@router.post(
    "/api/v1/telemetry/single",
    response_model=TelemetryIngestResponse,
    status_code=status.HTTP_200_OK,
)
async def ingest_single_telemetry(
    record: TelemetryRecord,
    session: AsyncSession = Depends(get_session_dependency),
    engine: EnergyEngine = Depends(get_engine),
):
    """Ingest a single sensor telemetry record."""
    return await ingest_telemetry_batch(
        TelemetryBatchRequest(records=[record]),
        session=session,
        engine=engine,
    )


# ── Energy State Snapshots ────────────────────────────────────────────

@router.get("/api/v1/energy/state/{station_id}", response_model=EnergyState)
async def get_latest_energy_state(
    station_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    engine: EnergyEngine = Depends(get_engine),
):
    """Get the latest real-time EnergyState snapshot for a station."""
    # Check in-memory engine cache first
    state = engine.get_latest_state(station_id)
    if state is not None:
        return state

    # Fallback to database
    state_repo = EnergyStateRepository(session)
    db_state = await state_repo.get_latest(station_id)
    if db_state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No energy state found for station '{station_id}'",
        )
    return db_state


@router.get("/api/v1/energy/state/{station_id}/history", response_model=list[EnergyState])
async def get_energy_state_history(
    station_id: str,
    limit: int = 50,
    session: AsyncSession = Depends(get_session_dependency),
):
    """Retrieve recent historical energy state snapshots."""
    state_repo = EnergyStateRepository(session)
    return await state_repo.get_history(station_id, limit=limit)


@router.get("/api/v1/energy/generation/{station_id}")
async def get_generation_breakdown(
    station_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    engine: EnergyEngine = Depends(get_engine),
):
    """Get current renewable and dispatchable generation breakdown."""
    state = await get_latest_energy_state(station_id, session, engine)
    return state.generation


@router.get("/api/v1/energy/load/{station_id}")
async def get_load_breakdown(
    station_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    engine: EnergyEngine = Depends(get_engine),
):
    """Get current station load consumption breakdown by priority."""
    state = await get_latest_energy_state(station_id, session, engine)
    return state.load


@router.get("/api/v1/energy/storage/{station_id}")
async def get_storage_breakdown(
    station_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    engine: EnergyEngine = Depends(get_engine),
):
    """Get current battery, hydrogen, and thermal storage states."""
    state = await get_latest_energy_state(station_id, session, engine)
    return {
        "battery": state.battery,
        "hydrogen": state.hydrogen,
        "thermal": state.thermal,
        "available_stored_energy_kwh": state.available_stored_energy_kwh,
        "available_dispatchable_power_kw": state.available_dispatchable_power_kw,
    }


# ── Alerts & Anomalies ────────────────────────────────────────────────

@router.get("/api/v1/energy/alerts/{station_id}")
async def get_active_alerts(
    station_id: str,
    session: AsyncSession = Depends(get_session_dependency),
):
    """Get all unacknowledged alerts and anomalies for a station."""
    alert_repo = AlertRepository(session)
    return await alert_repo.get_active(station_id)


@router.post("/api/v1/energy/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    session: AsyncSession = Depends(get_session_dependency),
):
    """Acknowledge an active operational alert."""
    alert_repo = AlertRepository(session)
    success = await alert_repo.acknowledge(alert_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert '{alert_id}' not found",
        )
    return {"alert_id": alert_id, "acknowledged": True}


# ── Agent Reasoning & What-If Queries ────────────────────────────────

@router.post("/api/v1/energy/query", response_model=AgentQueryResponse)
async def query_energy_agent(
    payload: AgentQueryRequest,
    agent: EnergyAgent = Depends(get_agent),
):
    """Ask a natural-language question about the station's energy situation."""
    result = agent.query(payload.station_id, payload.question)
    return AgentQueryResponse(
        station_id=payload.station_id,
        answer=result.get("answer", ""),
        intent=result.get("intent", "UNKNOWN"),
        metadata=result,
    )


@router.post("/api/v1/energy/evaluate-load", response_model=LoadEvaluationResponse)
async def evaluate_load_addition(
    payload: LoadEvaluationRequest,
    agent: EnergyAgent = Depends(get_agent),
):
    """Evaluate the physical microgrid feasibility of adding a new load."""
    result = agent.evaluate_load_addition(
        payload.station_id,
        payload.additional_kw,
        payload.duration_hours,
    )
    return LoadEvaluationResponse(
        station_id=payload.station_id,
        additional_kw=payload.additional_kw,
        duration_hours=payload.duration_hours,
        current_net_power_kw=result.get("current_net_power_kw", 0.0),
        projected_net_power_kw=result.get("projected_net_power_kw", 0.0),
        usable_battery_kwh=result.get("usable_battery_kwh", 0.0),
        energy_needed_kwh=result.get("energy_needed_kwh", 0.0),
        projected_runway_hours=result.get("projected_runway_hours"),
        verdict=result.get("verdict", "UNKNOWN"),
        feasible=result.get("feasible", False),
        reason=result.get("reason", ""),
    )


# ── Telemetry Simulator Trigger ───────────────────────────────────────

@router.post("/api/v1/energy/simulate/{station_id}", response_model=TelemetryIngestResponse)
async def trigger_simulation_tick(
    station_id: str,
    payload: SimulateRequest | None = None,
    session: AsyncSession = Depends(get_session_dependency),
    engine: EnergyEngine = Depends(get_engine),
):
    """Trigger a simulated sensor telemetry tick for a station."""
    if station_id not in _simulator_map:
        _simulator_map[station_id] = PolarStationSimulator(station_id=station_id)

    sim = _simulator_map[station_id]
    anomaly = payload.anomaly if payload else None
    batch = sim.generate_telemetry_batch(anomaly=anomaly)

    return await ingest_telemetry_batch(
        TelemetryBatchRequest(records=batch),
        session=session,
        engine=engine,
    )


# ── Module 01 Orchestrator Compatibility Routes ───────────────────────

@router.get("/energy/station/{station_id}/status")
async def get_m01_energy_status(
    station_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    engine: EnergyEngine = Depends(get_engine),
):
    """
    Contract endpoint consumed by Module 01 Orchestrator's EnergyClient.
    Matches the schema expected by M01 EnergyClient.get_energy_status.
    """
    state = engine.get_latest_state(station_id)
    if state is None:
        state_repo = EnergyStateRepository(session)
        state = await state_repo.get_latest(station_id)

    # If no data yet, provide polar baseline
    if state is None:
        return {
            "station_id": station_id,
            "generation": {
                "wind_kw": 180.0,
                "solar_kw": 120.0,
                "hydrogen_fuel_cell_kw": 0.0,
                "total_generation_kw": 300.0,
            },
            "consumption": {
                "total_demand_kw": 340.0,
                "deficit_kw": 40.0,
            },
            "storage": {
                "battery_kwh": 432.0,
                "battery_capacity_kwh": 600.0,
                "battery_soc_pct": 72.0,
                "hydrogen_kg": 162.0,
                "hydrogen_capacity_kg": 200.0,
            },
            "grid_status": "deficit",
        }

    deficit = abs(state.net_power_kw) if state.net_power_kw < 0 else 0.0
    grid_status = (
        "deficit" if state.status == EnergyStatus.DEFICIT
        else "surplus" if state.status == EnergyStatus.SURPLUS
        else "critical" if state.status == EnergyStatus.CRITICAL
        else "balanced"
    )

    return {
        "station_id": station_id,
        "generation": {
            "wind_kw": state.generation.wind_kw,
            "solar_kw": state.generation.solar_kw,
            "hydrogen_fuel_cell_kw": 0.0,
            "total_generation_kw": state.generation.total_generation_kw,
        },
        "consumption": {
            "total_demand_kw": state.load.total_load_kw,
            "deficit_kw": deficit,
        },
        "storage": {
            "battery_kwh": state.battery.usable_energy_kwh,
            "battery_capacity_kwh": state.battery.capacity_kwh,
            "battery_soc_pct": state.battery.soc_pct,
            "hydrogen_kg": state.hydrogen.current_level_kg,
            "hydrogen_capacity_kg": state.hydrogen.capacity_kg,
        },
        "grid_status": grid_status,
    }


@router.post("/energy/station/{station_id}/analyze")
async def analyze_generation_event_m01(
    station_id: str,
    event: dict[str, Any],
    engine: EnergyEngine = Depends(get_engine),
):
    """
    Contract endpoint consumed by Module 01 Orchestrator's EnergyClient.
    Analyzes a generation event and produces immediate risk and load adjustment assessment.
    """
    analysis = engine.analyze_generation_event(station_id, event)
    return {
        "station_id": station_id,
        "analysis": analysis,
    }
