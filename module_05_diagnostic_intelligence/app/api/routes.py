"""
Frost OS Module 05 — API Routes.

REST endpoints for diagnostic intelligence services.
Designed for M01 Orchestrator compatibility.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
import structlog

from app.api.schemas import (
    AnomalyResponse,
    DiagnosticResultResponse,
    EquipmentCapabilityResponse,
    EquipmentRegistration,
    FaultHypothesisResponse,
    HealthResponse,
    ServiceHealthResponse,
    StationHealthResponse,
    TelemetryBatchRequest,
)
from app.models.equipment import Equipment, EquipmentType, OperatingLimits

logger = structlog.get_logger(__name__)

router = APIRouter()


# ── Service Health ────────────────────────────────────────────────────

@router.get("/health", response_model=ServiceHealthResponse, tags=["health"])
async def health_check(request: Request) -> ServiceHealthResponse:
    """Service health check endpoint."""
    state = request.app.state
    uptime = time.time() - getattr(state, "start_time", time.time())
    engine = getattr(state, "diagnostic_engine", None)
    equipment_count = len(engine.get_all_equipment_ids()) if engine else 0

    return ServiceHealthResponse(
        service=state.settings.app_name,
        version=state.settings.app_version,
        status="healthy",
        environment=state.settings.environment,
        station_id=state.settings.station_id,
        uptime_seconds=round(uptime, 1),
        equipment_count=equipment_count,
        mock_mode=state.settings.mock_mode,
    )


# ── Diagnostics ──────────────────────────────────────────────────────

@router.post("/diagnostics/analyze", tags=["diagnostics"])
async def analyze_equipment(
    request: Request,
    body: TelemetryBatchRequest,
) -> DiagnosticResultResponse:
    """
    Run full diagnostic analysis on equipment telemetry.

    Accepts a batch of telemetry readings and returns anomaly detection,
    health assessment, fault hypotheses, and failure risk estimates.
    """
    agent = request.app.state.diagnostic_agent
    station_id = body.station_id or request.app.state.settings.station_id

    telemetry = [
        {
            "signal_name": r.signal_name,
            "value": r.value,
            "timestamp": r.timestamp or datetime.now(timezone.utc),
            "unit": r.unit,
            "quality": r.quality,
        }
        for r in body.readings
    ]

    result = await agent.analyze_equipment(
        equipment_id=body.equipment_id,
        station_id=station_id,
        telemetry=telemetry,
    )

    return DiagnosticResultResponse(
        diagnostic_id=result.diagnostic_id,
        equipment_id=result.equipment_id,
        station_id=result.station_id,
        timestamp=result.timestamp,
        health_score=result.health_score,
        health_state=result.health_state.value,
        anomaly_detected=result.anomaly_detected,
        anomalies=[
            AnomalyResponse(
                anomaly_id=a.anomaly_id,
                type=a.type.value,
                severity=a.severity.value,
                score=a.score,
                confidence=a.confidence,
                observed_value=a.observed_value,
                expected_value=a.expected_value,
                residual=a.residual,
                signals=a.signals,
                possible_causes=a.possible_causes,
                detection_layer=a.detection_layer,
            )
            for a in result.anomalies
        ],
        fault_hypotheses=[
            FaultHypothesisResponse(
                fault=fh.fault,
                confidence=fh.confidence,
                evidence=fh.evidence,
                description=fh.description,
                recommended_investigation=fh.recommended_investigation,
                is_confirmed=fh.is_confirmed,
            )
            for fh in result.fault_hypotheses
        ],
        failure_risk=result.failure_risk.model_dump(mode="json") if result.failure_risk else None,
        degradation=result.degradation,
        data_quality=result.data_quality.value,
        recommended_investigation=result.recommended_investigation,
        model_version=result.model_version,
    )


@router.get("/diagnostics/{equipment_id}", tags=["diagnostics"])
async def get_latest_diagnostic(
    request: Request,
    equipment_id: str,
) -> dict[str, Any]:
    """Get the latest diagnostic result for an equipment."""
    engine = request.app.state.diagnostic_engine
    result = engine.get_latest_result(equipment_id)

    if result is None:
        raise HTTPException(status_code=404, detail=f"No diagnostic data for equipment {equipment_id}")

    return result.to_dict()


@router.get("/diagnostics/{equipment_id}/explain", tags=["diagnostics"])
async def explain_diagnostic(
    request: Request,
    equipment_id: str,
) -> dict[str, str]:
    """Get human-readable diagnostic explanation."""
    agent = request.app.state.diagnostic_agent
    explanation = agent.explain_diagnostic(equipment_id)
    return {"equipment_id": equipment_id, "explanation": explanation}


# ── Equipment Registration ───────────────────────────────────────────

@router.post("/equipment/register", tags=["equipment"])
async def register_equipment(
    request: Request,
    body: EquipmentRegistration,
) -> dict[str, str]:
    """Register a new equipment asset for diagnostic monitoring."""
    engine = request.app.state.diagnostic_engine

    try:
        eq_type = EquipmentType(body.equipment_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown equipment type: {body.equipment_type}")

    limits = OperatingLimits(**body.operating_limits) if body.operating_limits else OperatingLimits()

    equipment = Equipment(
        equipment_id=body.equipment_id,
        station_id=body.station_id,
        type=eq_type,
        manufacturer=body.manufacturer,
        model=body.model,
        rated_power_kw=body.rated_power_kw,
        capacity=body.capacity,
        location=body.location,
        operating_limits=limits,
    )

    engine.register_equipment(equipment)

    return {
        "status": "registered",
        "equipment_id": body.equipment_id,
        "equipment_type": eq_type.value,
    }


@router.get("/equipment", tags=["equipment"])
async def list_equipment(request: Request) -> dict[str, Any]:
    """List all registered equipment."""
    engine = request.app.state.diagnostic_engine
    equipment_ids = engine.get_all_equipment_ids()
    return {"equipment_count": len(equipment_ids), "equipment_ids": equipment_ids}


# ── Station Health ────────────────────────────────────────────────────

@router.get("/station/{station_id}/health", tags=["station"])
async def get_station_health(
    request: Request,
    station_id: str,
) -> StationHealthResponse:
    """Get station-wide health summary."""
    agent = request.app.state.diagnostic_agent
    summary = await agent.get_station_health(station_id)
    return StationHealthResponse(**summary)


# ── M01 Orchestrator Interface ────────────────────────────────────────

@router.post("/diagnostics/m01/diagnose", tags=["orchestrator"])
async def m01_diagnose(
    request: Request,
    body: dict[str, Any],
) -> dict[str, Any]:
    """
    M01 Orchestrator diagnostic request handler.

    Accepts orchestrator-formatted requests and returns
    diagnostics in the format M01 DiagnosticClient expects.
    """
    agent = request.app.state.diagnostic_agent
    station_id = body.get("station_id", request.app.state.settings.station_id)
    return await agent.diagnose_for_m01(station_id, body)


# ── M06 Optimization Interface ────────────────────────────────────────

@router.get("/equipment/{equipment_id}/capability", tags=["optimization"])
async def get_equipment_capability(
    request: Request,
    equipment_id: str,
) -> EquipmentCapabilityResponse:
    """
    Equipment capability for M06 optimization.

    M05 describes capability/risk; M06 decides allocation.
    """
    agent = request.app.state.diagnostic_agent
    cap = await agent.get_equipment_capability_for_m06(equipment_id)
    return EquipmentCapabilityResponse(**cap)


# ── Events ────────────────────────────────────────────────────────────

@router.get("/events/recent", tags=["events"])
async def get_recent_events(
    request: Request,
    limit: int = 50,
) -> dict[str, Any]:
    """Get recently published diagnostic events."""
    publisher = request.app.state.event_publisher
    events = publisher.get_published_events(limit)
    return {"event_count": len(events), "events": events}
