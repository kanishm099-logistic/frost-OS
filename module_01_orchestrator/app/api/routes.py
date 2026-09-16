"""
Frost OS Module 01 — API Routes.

FastAPI router defining all orchestrator endpoints including
event ingestion, decision retrieval, action plan management,
authorization, and WebSocket live updates.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.api.schemas import (
    ActionPlanResponse,
    AuthorizationRequest,
    DecisionResponse,
    EventCreateRequest,
    EventResponse,
    HealthResponse,
    PipelineResponse,
    PlannedActionResponse,
    SystemStatusResponse,
    TransitionResponse,
    WorkflowRunResponse,
)
from app.models.event import StationEvent
from app.storage.database import get_session_dependency
from app.storage.repository import (
    ActionPlanRepository,
    AuditRepository,
    DecisionRepository,
    EventRepository,
    WorkflowRunRepository,
)

logger = structlog.get_logger(__name__)

router = APIRouter()

# ── Module-level references (set during app startup) ──────────────────
_orchestrator = None
_workflow_engine = None
_ws_manager = None
_settings = None
_priority_queue = None
_start_time = time.monotonic()


def configure_routes(orchestrator, workflow_engine, ws_manager, settings, priority_queue=None):
    """Configure route dependencies (called during app startup)."""
    global _orchestrator, _workflow_engine, _ws_manager, _settings, _priority_queue
    _orchestrator = orchestrator
    _workflow_engine = workflow_engine
    _ws_manager = ws_manager
    _settings = settings
    _priority_queue = priority_queue


# ── WebSocket Manager ─────────────────────────────────────────────────

class WebSocketManager:
    """Manages active WebSocket connections for live updates."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connected WebSocket clients."""
        disconnected = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Global instance
ws_manager = WebSocketManager()


# ── Health Check ──────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check(session: AsyncSession = Depends(get_session_dependency)):
    """Health check endpoint — verifies DB and Redis connectivity."""
    db_status = "healthy"
    redis_status = "healthy"

    try:
        from sqlalchemy import text
        await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    # Redis check is best-effort
    try:
        from app.main import _redis_client
        if _redis_client:
            await _redis_client.ping()
    except Exception:
        redis_status = "unhealthy"

    overall = "healthy" if db_status == "healthy" and redis_status == "healthy" else "degraded"

    return HealthResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
        timestamp=datetime.now(timezone.utc),
    )


# ── System Status ─────────────────────────────────────────────────────

@router.get("/orchestrator/status", response_model=SystemStatusResponse, tags=["Status"])
async def system_status(session: AsyncSession = Depends(get_session_dependency)):
    """System status overview."""
    workflows = _workflow_engine.list_workflows() if _workflow_engine else []

    db_status = "healthy"
    redis_status = "healthy"
    try:
        from sqlalchemy import text
        await session.execute(text("SELECT 1"))
    except Exception:
        db_status = "unhealthy"

    try:
        from app.main import _redis_client
        if _redis_client:
            await _redis_client.ping()
    except Exception:
        redis_status = "unhealthy"

    return SystemStatusResponse(
        service="frost-orchestrator",
        status="operational",
        station_id=_settings.station_id if _settings else "unknown",
        mock_mode=_settings.mock_mode if _settings else True,
        database=db_status,
        redis=redis_status,
        registered_workflows=workflows,
        uptime_seconds=time.monotonic() - _start_time,
    )


# ── Events ────────────────────────────────────────────────────────────

@router.post(
    "/orchestrator/events",
    response_model=PipelineResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Events"],
)
async def ingest_event(
    request: EventCreateRequest,
    session: AsyncSession = Depends(get_session_dependency),
):
    """
    Ingest a new station event and trigger the orchestration pipeline.

    Returns immediately with the decision ID. The pipeline runs
    asynchronously. Use WebSocket or polling for updates.
    """
    if _orchestrator is None:
        raise HTTPException(500, detail="Orchestrator not initialized")

    # Build domain event
    event = StationEvent(
        source=request.source,
        event_type=request.event_type,
        severity=request.severity,
        station_id=request.station_id,
        payload=request.payload,
        correlation_id=request.correlation_id or None,
    )

    # Create repositories from session
    event_repo = EventRepository(session)
    decision_repo = DecisionRepository(session)
    plan_repo = ActionPlanRepository(session)
    audit_repo = AuditRepository(session)
    workflow_repo = WorkflowRunRepository(session)

    # Check for duplicate event
    if await event_repo.exists(event.event_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Event {event.event_id} already exists",
        )

    # Process through orchestration pipeline
    result = await _orchestrator.process_event(
        event=event,
        event_repo=event_repo,
        decision_repo=decision_repo,
        plan_repo=plan_repo,
        audit_repo=audit_repo,
        workflow_repo=workflow_repo,
    )

    if _priority_queue:
        _priority_queue.record_processed_event(event, result)

    return PipelineResponse(
        decision_id=result["decision_id"],
        plan_id=result.get("plan_id"),
        status=result["status"],
        requires_authorization=result.get("requires_authorization", False),
        error=result.get("error"),
    )


@router.get("/orchestrator/priority-queue", tags=["Priority Process"])
async def get_priority_queue_status():
    """Retrieve current priority-based event queue status, metrics, and backlog preview."""
    if _priority_queue:
        return _priority_queue.get_status()
    return {
        "queue_depth": 0,
        "counts_by_severity": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0},
        "currently_processing": None,
        "queued_events_preview": [],
        "total_processed": 0,
        "recent_processed": [],
    }


@router.get("/orchestrator/events/{event_id}", response_model=EventResponse, tags=["Events"])
async def get_event(event_id: str, session: AsyncSession = Depends(get_session_dependency)):
    """Retrieve event details by ID."""
    repo = EventRepository(session)
    record = await repo.get_by_id(event_id)
    if record is None:
        raise HTTPException(404, detail=f"Event {event_id} not found")

    return EventResponse(
        event_id=str(record.event_id),
        timestamp=record.timestamp,
        source=record.source,
        event_type=record.event_type.value,
        severity=record.severity.value,
        station_id=record.station_id,
        payload=record.payload or {},
        correlation_id=record.correlation_id,
    )


# ── Decisions ─────────────────────────────────────────────────────────

@router.get("/orchestrator/decisions/{decision_id}", response_model=DecisionResponse, tags=["Decisions"])
async def get_decision(decision_id: str, session: AsyncSession = Depends(get_session_dependency)):
    """Retrieve decision details with transition history."""
    decision_repo = DecisionRepository(session)
    record = await decision_repo.get_by_id(decision_id)
    if record is None:
        raise HTTPException(404, detail=f"Decision {decision_id} not found")

    transitions = await decision_repo.get_transitions(decision_id)
    transition_responses = [
        TransitionResponse(
            from_status=t.from_status.value,
            to_status=t.to_status.value,
            reason=t.reason,
            actor=t.actor,
            timestamp=t.timestamp,
        )
        for t in transitions
    ]

    return DecisionResponse(
        decision_id=str(record.decision_id),
        event_id=str(record.event_id),
        station_id=record.station_id,
        correlation_id=record.correlation_id,
        status=record.status.value,
        workflow_name=record.workflow_name,
        action_plan_id=str(record.action_plan_id) if record.action_plan_id else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
        transitions=transition_responses,
    )


# ── Action Plans ──────────────────────────────────────────────────────

@router.get("/orchestrator/action-plans/{plan_id}", response_model=ActionPlanResponse, tags=["Action Plans"])
async def get_action_plan(plan_id: str, session: AsyncSession = Depends(get_session_dependency)):
    """Retrieve action plan details."""
    repo = ActionPlanRepository(session)
    record = await repo.get_by_id(plan_id)
    if record is None:
        raise HTTPException(404, detail=f"Action plan {plan_id} not found")

    # Parse actions from JSON
    actions = []
    if record.actions:
        for a in record.actions:
            actions.append(PlannedActionResponse(
                action_id=a.get("action_id", ""),
                action_type=a.get("action_type", ""),
                target=a.get("target", ""),
                description=a.get("description", ""),
                parameters=a.get("parameters", {}),
                priority=a.get("priority", 0),
                estimated_impact_kwh=a.get("estimated_impact_kwh", 0.0),
                reversible=a.get("reversible", True),
            ))

    return ActionPlanResponse(
        plan_id=str(record.plan_id),
        trigger_event_id=str(record.trigger_event_id),
        decision_id=str(record.decision_id),
        station_id=record.station_id,
        status=record.status.value,
        reason=record.reason,
        actions=actions,
        projected_reserve_kwh=record.projected_reserve_kwh,
        required_reserve_kwh=record.required_reserve_kwh,
        safety_status=record.safety_status.value,
        requires_authorization=record.requires_authorization,
        is_emergency=record.is_emergency,
        created_at=record.created_at,
        expires_at=record.expires_at,
    )


@router.post("/orchestrator/action-plans/{plan_id}/authorize", tags=["Authorization"])
async def authorize_plan(
    plan_id: str,
    request: AuthorizationRequest,
    session: AsyncSession = Depends(get_session_dependency),
):
    """
    Authorize an action plan for execution.

    Only plans in AWAITING_AUTHORIZATION status can be authorized.
    """
    if _orchestrator is None:
        raise HTTPException(500, detail="Orchestrator not initialized")

    decision_repo = DecisionRepository(session)
    plan_repo = ActionPlanRepository(session)
    audit_repo = AuditRepository(session)
    event_repo = EventRepository(session)

    try:
        result = await _orchestrator.authorize_plan(
            plan_id=plan_id,
            authorized_by=request.authorized_by,
            reason=request.reason,
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
            event_repo=event_repo,
        )
        return result
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))


@router.post("/orchestrator/action-plans/{plan_id}/reject", tags=["Authorization"])
async def reject_plan(
    plan_id: str,
    request: AuthorizationRequest,
    session: AsyncSession = Depends(get_session_dependency),
):
    """
    Reject an action plan.

    Only plans in AWAITING_AUTHORIZATION status can be rejected.
    """
    if _orchestrator is None:
        raise HTTPException(500, detail="Orchestrator not initialized")

    decision_repo = DecisionRepository(session)
    plan_repo = ActionPlanRepository(session)
    audit_repo = AuditRepository(session)

    try:
        result = await _orchestrator.reject_plan(
            plan_id=plan_id,
            rejected_by=request.authorized_by,
            reason=request.reason,
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
        )
        return result
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))


# ── Workflows ─────────────────────────────────────────────────────────

@router.get("/orchestrator/workflows/{workflow_run_id}", response_model=WorkflowRunResponse, tags=["Workflows"])
async def get_workflow_run(
    workflow_run_id: str,
    session: AsyncSession = Depends(get_session_dependency),
):
    """Retrieve workflow run details."""
    repo = WorkflowRunRepository(session)
    record = await repo.get_by_id(workflow_run_id)
    if record is None:
        raise HTTPException(404, detail=f"Workflow run {workflow_run_id} not found")

    return WorkflowRunResponse(
        workflow_run_id=str(record.workflow_run_id),
        decision_id=str(record.decision_id),
        workflow_name=record.workflow_name,
        station_id=record.station_id,
        correlation_id=record.correlation_id,
        status=record.status,
        started_at=record.started_at,
        completed_at=record.completed_at,
        error_message=record.error_message,
    )


# ── WebSocket ─────────────────────────────────────────────────────────

@router.websocket("/orchestrator/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for live orchestration updates.

    Streams events, decision status changes, authorization requests,
    and execution results in real-time.
    """
    await ws_manager.connect(websocket)
    await logger.ainfo("WebSocket client connected", total=ws_manager.connection_count)

    try:
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to Frost Orchestrator live updates",
            "station_id": _settings.station_id if _settings else "unknown",
        })

        # Keep connection alive — listen for client messages
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                # Handle ping/pong
                if data == "ping":
                    await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat"})

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        await logger.ainfo("WebSocket client disconnected", total=ws_manager.connection_count)
    except Exception as exc:
        ws_manager.disconnect(websocket)
        await logger.awarning("WebSocket error", error=str(exc))
