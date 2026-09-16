"""
Frost OS Module 02 — API Routes.

Implements REST endpoints for mission management, classification, profiling,
lifecycle state transitions, and integration hooks for Module 01 and Module 06.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.agents.mission_agent import MissionAgent
from app.api.schemas import (
    ActiveMissionsResponse,
    HealthResponse,
    ImpactAnalysisRequest,
    MissionClassifyRequest,
    MissionCreateRequest,
    MissionListResponse,
    MissionPrioritiesResponse,
    MissionProfileResponse,
    MissionResponse,
    MissionStateActionRequest,
    MissionUpdateRequest,
    SystemStatusResponse,
)
from app.config.settings import Settings
from app.core.mission_engine import MissionEngine
from app.events.event_types import MissionEventType
from app.events.publisher import MissionEventPublisher
from app.models.mission import Flexibility, Mission, MissionState, MissionType
from app.models.priority import PriorityLevel
from app.storage.database import get_session_dependency
from app.storage.repository import AuditRepository, MissionRepository

logger = structlog.get_logger(__name__)

router = APIRouter()

# Service dependencies (populated during app lifespan)
_settings: Settings | None = None
_engine: MissionEngine | None = None
_agent: MissionAgent | None = None
_publisher: MissionEventPublisher | None = None


def set_dependencies(
    settings: Settings,
    engine: MissionEngine,
    agent: MissionAgent,
    publisher: MissionEventPublisher,
) -> None:
    """Set module-level dependencies."""
    global _settings, _engine, _agent, _publisher
    _settings = settings
    _engine = engine
    _agent = agent
    _publisher = publisher


def get_engine() -> MissionEngine:
    if _engine is None:
        raise HTTPException(status_code=500, detail="MissionEngine not initialized")
    return _engine


def get_agent() -> MissionAgent:
    if _agent is None:
        raise HTTPException(status_code=500, detail="MissionAgent not initialized")
    return _agent


def get_publisher() -> MissionEventPublisher:
    if _publisher is None:
        raise HTTPException(status_code=500, detail="EventPublisher not initialized")
    return _publisher


# ── Health & Status ───────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health():
    """Service liveness probe."""
    return HealthResponse()


@router.get("/mission-intelligence/status", response_model=SystemStatusResponse, tags=["Status"])
async def system_status(
    station_id: str = Query(default="FROST-STATION-ALPHA"),
    session: AsyncSession = Depends(get_session_dependency),
):
    """Retrieve operational status and aggregate workload metrics."""
    repo = MissionRepository(session)
    missions = await repo.list_all_domain(station_id=station_id)

    active_statuses = {MissionState.SCHEDULED, MissionState.READY, MissionState.RUNNING}
    active_missions = [m for m in missions if m.status in active_statuses]

    total_demand = sum(m.required_power_kw for m in active_missions)
    total_protected = sum(m.protected_energy_kwh for m in active_missions)

    return SystemStatusResponse(
        service="frost-mission-intelligence",
        status="operational",
        station_id=station_id,
        total_missions=len(missions),
        active_missions=len(active_missions),
        total_demand_kw=round(total_demand, 2),
        total_protected_energy_kwh=round(total_protected, 2),
        environment=_settings.environment if _settings else "unknown",
    )


# ── CRUD Endpoints ────────────────────────────────────────────────────

@router.post("/missions", response_model=MissionResponse, status_code=status.HTTP_201_CREATED, tags=["Missions"])
async def create_mission(
    req: MissionCreateRequest,
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
    publisher: MissionEventPublisher = Depends(get_publisher),
):
    """Create a new mission, enrich its energy/buffer profiles, and persist it."""
    repo = MissionRepository(session)
    audit = AuditRepository(session)

    # Auto-classify type and priority if not explicitly specified
    m_type = req.type
    m_priority = req.priority
    if m_type is None or m_priority is None:
        classification = engine.classifier.classify(f"{req.name} {req.description}")
        m_type = m_type or classification.mission_type
        m_priority = m_priority or classification.suggested_priority

    mission = Mission(
        station_id=req.station_id,
        name=req.name,
        description=req.description,
        type=m_type,
        priority=m_priority,
        required_power_kw=req.required_power_kw,
        min_power_kw=req.min_power_kw or round(req.required_power_kw * 0.8, 2),
        max_power_kw=req.max_power_kw or round(req.required_power_kw * 1.2, 2),
        expected_duration_minutes=req.expected_duration_minutes,
        deadline=req.deadline,
        flexibility=req.flexibility,
        dependencies=req.dependencies,
        earliest_start=req.earliest_start,
        latest_start=req.latest_start,
        status=MissionState.CREATED,
        metadata=req.metadata,
    )

    # Enrich mission calculations (energy, buffer, windows)
    enriched = engine.enrich_mission(mission)

    # Persist
    await repo.save(enriched)
    correlation_id = str(uuid.uuid4())
    await audit.log(
        station_id=enriched.station_id,
        actor="api",
        action="mission_created",
        correlation_id=correlation_id,
        mission_id=enriched.mission_id,
        details={"name": enriched.name, "priority": enriched.priority.value, "type": enriched.type.value},
    )

    # Publish event
    await publisher.publish_lifecycle(
        event_type=MissionEventType.MISSION_CREATED,
        station_id=enriched.station_id,
        mission_id=enriched.mission_id,
        correlation_id=correlation_id,
        payload={
            "name": enriched.name,
            "priority": enriched.priority.value,
            "type": enriched.type.value,
            "required_power_kw": enriched.required_power_kw,
            "min_power_kw": enriched.min_power_kw,
            "protected_energy_kwh": enriched.protected_energy_kwh,
        },
    )

    return MissionResponse(mission=enriched)


@router.get("/missions", response_model=MissionListResponse, tags=["Missions"])
async def list_missions(
    station_id: str | None = Query(default=None),
    status: MissionState | None = Query(default=None),
    session: AsyncSession = Depends(get_session_dependency),
):
    """List all missions, optionally filtered by station_id or status."""
    repo = MissionRepository(session)
    missions = await repo.list_all_domain(station_id=station_id, status=status)
    return MissionListResponse(total=len(missions), missions=missions)


@router.get("/missions/{mission_id}", response_model=MissionResponse, tags=["Missions"])
async def get_mission(
    mission_id: str,
    session: AsyncSession = Depends(get_session_dependency),
):
    """Retrieve details of a single mission."""
    repo = MissionRepository(session)
    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")
    return MissionResponse(mission=mission)


@router.patch("/missions/{mission_id}", response_model=MissionResponse, tags=["Missions"])
async def update_mission(
    mission_id: str,
    req: MissionUpdateRequest,
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
    publisher: MissionEventPublisher = Depends(get_publisher),
):
    """Update fields of an existing mission and re-calculate energy/buffer values."""
    repo = MissionRepository(session)
    audit = AuditRepository(session)

    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    # Apply partial updates
    if req.name is not None:
        mission.name = req.name
    if req.description is not None:
        mission.description = req.description
    if req.type is not None:
        mission.type = req.type
    if req.priority is not None:
        mission.priority = req.priority
    if req.required_power_kw is not None:
        mission.required_power_kw = req.required_power_kw
        if req.max_power_kw is None and mission.required_power_kw > mission.max_power_kw:
            mission.max_power_kw = round(mission.required_power_kw * 1.2, 2)
        if req.min_power_kw is None and mission.required_power_kw < mission.min_power_kw:
            mission.min_power_kw = round(mission.required_power_kw * 0.8, 2)
    if req.min_power_kw is not None:
        mission.min_power_kw = req.min_power_kw
    if req.max_power_kw is not None:
        mission.max_power_kw = req.max_power_kw
    if req.expected_duration_minutes is not None:
        mission.expected_duration_minutes = req.expected_duration_minutes
    if req.deadline is not None:
        mission.deadline = req.deadline
    if req.flexibility is not None:
        mission.flexibility = req.flexibility
    if req.status is not None:
        mission.status = req.status
    if req.dependencies is not None:
        mission.dependencies = req.dependencies
    if req.metadata is not None:
        mission.metadata.update(req.metadata)

    # Re-enrich calculations
    enriched = engine.enrich_mission(mission)
    await repo.update(enriched)

    correlation_id = str(uuid.uuid4())
    await audit.log(
        station_id=enriched.station_id,
        actor="api",
        action="mission_updated",
        correlation_id=correlation_id,
        mission_id=enriched.mission_id,
    )

    await publisher.publish_lifecycle(
        event_type=MissionEventType.MISSION_UPDATED,
        station_id=enriched.station_id,
        mission_id=enriched.mission_id,
        correlation_id=correlation_id,
    )

    return MissionResponse(mission=enriched)


@router.delete("/missions/{mission_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Missions"])
async def delete_mission(
    mission_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    publisher: MissionEventPublisher = Depends(get_publisher),
):
    """Delete a mission."""
    repo = MissionRepository(session)
    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    await repo.delete(mission_id)

    correlation_id = str(uuid.uuid4())
    await publisher.publish_lifecycle(
        event_type=MissionEventType.MISSION_CANCELLED,
        station_id=mission.station_id,
        mission_id=mission_id,
        correlation_id=correlation_id,
        payload={"reason": "deleted_by_operator"},
    )


# ── Profile & Analysis Endpoints ──────────────────────────────────────

@router.post("/missions/{mission_id}/profile", response_model=MissionProfileResponse, tags=["Profile"])
async def generate_mission_profile(
    mission_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
    agent: MissionAgent = Depends(get_agent),
):
    """Generate structured MissionProfile consumed by Module 06 Optimizer."""
    repo = MissionRepository(session)
    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    profile = engine.create_profile(mission)
    explanation = agent.explain_mission_profile(profile)

    return MissionProfileResponse(profile=profile, explanation=explanation)


@router.post("/missions/{mission_id}/classify", tags=["Analysis"])
async def classify_mission(
    mission_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
):
    """Run rule-based classification on mission name and description."""
    repo = MissionRepository(session)
    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    result = engine.classifier.classify(f"{mission.name} {mission.description}")
    return result


@router.get("/missions/{mission_id}/energy-profile", tags=["Analysis"])
async def get_energy_profile(
    mission_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
):
    """Get the power and energy breakdown for a mission."""
    repo = MissionRepository(session)
    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    enriched = engine.enrich_mission(mission)
    curtailment = engine.energy_estimator.calculate_curtailment_potential(enriched)

    return {
        "mission_id": enriched.mission_id,
        "name": enriched.name,
        "power_profile": {
            "required_power_kw": enriched.required_power_kw,
            "min_power_kw": enriched.min_power_kw,
            "max_power_kw": enriched.max_power_kw,
            "curtailment_potential_kw": curtailment,
        },
        "energy_profile": {
            "duration_hours": enriched.expected_duration_minutes / 60.0,
            "base_energy_kwh": enriched.energy_required_kwh,
            "buffer_kwh": enriched.buffer_kwh,
            "buffer_factor": engine.buffer_engine.get_buffer_factor(enriched.priority),
            "protected_energy_kwh": enriched.protected_energy_kwh,
        },
    }


@router.get("/missions/{mission_id}/priority", tags=["Analysis"])
async def get_priority_details(
    mission_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
):
    """Get multi-criteria scheduling score and breakdown for a mission."""
    repo = MissionRepository(session)
    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    score_result = engine.priority_engine.calculate_score(mission)
    return {
        "mission_id": mission.mission_id,
        "name": mission.name,
        "priority": mission.priority.value,
        "is_protected": mission.priority.is_protected or score_result.is_protected_override,
        "scheduling_score": score_result.total_score,
        "breakdown": score_result.breakdown,
        "explanation": score_result.explanation,
    }


@router.get("/missions/{mission_id}/dependencies", tags=["Analysis"])
async def get_dependencies(
    mission_id: str,
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
):
    """Check prerequisite dependency status for a mission."""
    repo = MissionRepository(session)
    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    all_missions = {m.mission_id: m for m in await repo.list_all_domain(station_id=mission.station_id)}
    satisfied, unmet = engine.check_dependencies(mission, all_missions)

    return {
        "mission_id": mission.mission_id,
        "dependencies": mission.dependencies,
        "all_dependencies_satisfied": satisfied,
        "unmet_dependencies": unmet,
    }


# ── Lifecycle State Actions ───────────────────────────────────────────

@router.post("/missions/{mission_id}/start", response_model=MissionResponse, tags=["Lifecycle"])
async def start_mission(
    mission_id: str,
    req: MissionStateActionRequest = MissionStateActionRequest(),
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
    publisher: MissionEventPublisher = Depends(get_publisher),
):
    """Transition mission to RUNNING state."""
    repo = MissionRepository(session)
    audit = AuditRepository(session)

    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    all_missions = {m.mission_id: m for m in await repo.list_all_domain(station_id=mission.station_id)}
    valid, msg = engine.validate_transition(mission, MissionState.RUNNING, all_missions)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    prev_state = mission.status
    mission.status = MissionState.RUNNING
    await repo.update(mission)
    await repo.record_transition(mission_id, prev_state, MissionState.RUNNING, req.reason, req.actor)

    correlation_id = str(uuid.uuid4())
    await audit.log(mission.station_id, req.actor, "mission_started", correlation_id, mission_id)
    await publisher.publish_lifecycle(
        MissionEventType.MISSION_STARTED,
        mission.station_id,
        mission_id,
        correlation_id,
    )

    return MissionResponse(mission=mission)


@router.post("/missions/{mission_id}/pause", response_model=MissionResponse, tags=["Lifecycle"])
async def pause_mission(
    mission_id: str,
    req: MissionStateActionRequest = MissionStateActionRequest(),
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
    publisher: MissionEventPublisher = Depends(get_publisher),
):
    """Transition mission to PAUSED state."""
    repo = MissionRepository(session)
    audit = AuditRepository(session)

    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    valid, msg = engine.validate_transition(mission, MissionState.PAUSED)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    prev_state = mission.status
    mission.status = MissionState.PAUSED
    await repo.update(mission)
    await repo.record_transition(mission_id, prev_state, MissionState.PAUSED, req.reason, req.actor)

    correlation_id = str(uuid.uuid4())
    await audit.log(mission.station_id, req.actor, "mission_paused", correlation_id, mission_id)
    await publisher.publish_lifecycle(
        MissionEventType.MISSION_PAUSED,
        mission.station_id,
        mission_id,
        correlation_id,
    )

    return MissionResponse(mission=mission)


@router.post("/missions/{mission_id}/complete", response_model=MissionResponse, tags=["Lifecycle"])
async def complete_mission(
    mission_id: str,
    req: MissionStateActionRequest = MissionStateActionRequest(),
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
    publisher: MissionEventPublisher = Depends(get_publisher),
):
    """Transition mission to COMPLETED state."""
    repo = MissionRepository(session)
    audit = AuditRepository(session)

    mission = await repo.get_domain_by_id(mission_id)
    if not mission:
        raise HTTPException(status_code=404, detail=f"Mission {mission_id} not found")

    valid, msg = engine.validate_transition(mission, MissionState.COMPLETED)
    if not valid:
        raise HTTPException(status_code=400, detail=msg)

    prev_state = mission.status
    mission.status = MissionState.COMPLETED
    await repo.update(mission)
    await repo.record_transition(mission_id, prev_state, MissionState.COMPLETED, req.reason, req.actor)

    correlation_id = str(uuid.uuid4())
    await audit.log(mission.station_id, req.actor, "mission_completed", correlation_id, mission_id)
    await publisher.publish_lifecycle(
        MissionEventType.MISSION_COMPLETED,
        mission.station_id,
        mission_id,
        correlation_id,
    )

    return MissionResponse(mission=mission)


# ── Module 01 & Module 06 Integration Routes ─────────────────────────

@router.get("/missions/station/{station_id}/active", tags=["Integration-M01"])
async def get_active_missions_m01(
    station_id: str,
    session: AsyncSession = Depends(get_session_dependency),
):
    """M01 Orchestrator compatibility endpoint: active missions list."""
    repo = MissionRepository(session)
    missions = await repo.list_all_domain(station_id=station_id)

    # Active missions in scheduled, ready, or running states
    active_statuses = {MissionState.SCHEDULED, MissionState.READY, MissionState.RUNNING}
    active = [m for m in missions if m.status in active_statuses]

    formatted = [
        {
            "mission_id": m.mission_id,
            "name": m.name,
            "priority": m.priority.value,
            "power_requirement_kw": m.required_power_kw,
            "critical": m.priority.is_protected,
            "can_reduce": m.flexibility in (Flexibility.PARTIALLY_FLEXIBLE, Flexibility.FLEXIBLE),
            "minimum_kw": m.min_power_kw,
            "protected_energy_kwh": m.protected_energy_kwh,
        }
        for m in active
    ]

    return {
        "status": "success",
        "module_name": "mission",
        "data": {
            "station_id": station_id,
            "active_missions": formatted,
            "total_demand_kw": round(sum(m.required_power_kw for m in active), 2),
        },
    }


@router.get("/missions/station/{station_id}/priorities", tags=["Integration-M01"])
async def get_mission_priorities_m01(
    station_id: str,
    session: AsyncSession = Depends(get_session_dependency),
):
    """M01 Orchestrator compatibility endpoint: priority breakdown."""
    repo = MissionRepository(session)
    missions = await repo.list_all_domain(station_id=station_id)

    active_statuses = {MissionState.SCHEDULED, MissionState.READY, MissionState.RUNNING}
    active = [m for m in missions if m.status in active_statuses]

    non_reducible = sum(m.required_power_kw for m in active if m.priority == PriorityLevel.P0) + sum(
        m.min_power_kw for m in active if m.priority == PriorityLevel.P1
    )
    total_kw = sum(m.required_power_kw for m in active)
    reducible = max(0.0, total_kw - non_reducible)

    return {
        "status": "success",
        "module_name": "mission",
        "data": {
            "station_id": station_id,
            "priority_order": ["P0", "P1", "P2", "P3", "P4"],
            "non_reducible_kw": round(non_reducible, 2),
            "reducible_kw": round(reducible, 2),
            "total_kw": round(total_kw, 2),
        },
    }


@router.post("/missions/station/{station_id}/impact-analysis", tags=["Integration-M01"])
async def analyze_impact_m01(
    station_id: str,
    req: ImpactAnalysisRequest,
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
):
    """M01 Orchestrator compatibility endpoint: assess event impact on active workloads."""
    repo = MissionRepository(session)
    missions = await repo.list_all_domain(station_id=station_id)

    active_statuses = {MissionState.SCHEDULED, MissionState.READY, MissionState.RUNNING}
    active = [m for m in missions if m.status in active_statuses]

    current_gen = float(req.payload.get("current_kw", 0.0))
    previous_gen = float(req.payload.get("previous_kw", current_gen))

    impact_assessment = engine.assess_generation_impact(
        active_missions=active,
        station_id=station_id,
        current_generation_kw=current_gen,
        baseline_generation_kw=previous_gen,
    )

    return {
        "status": "success",
        "module_name": "mission",
        "data": {
            "station_id": station_id,
            "impact_assessment": impact_assessment,
        },
    }


@router.get("/missions/profiles/active", tags=["Integration-M06"])
async def get_active_profiles_m06(
    station_id: str = Query(default="FROST-STATION-ALPHA"),
    session: AsyncSession = Depends(get_session_dependency),
    engine: MissionEngine = Depends(get_engine),
):
    """M06 Optimizer endpoint: returns active MissionProfiles ready for scheduling."""
    repo = MissionRepository(session)
    missions = await repo.list_all_domain(station_id=station_id)

    active_statuses = {MissionState.SCHEDULED, MissionState.READY, MissionState.RUNNING}
    active = [m for m in missions if m.status in active_statuses]

    profiles = [engine.create_profile(m) for m in active]
    # Sort by scheduling score descending (highest priority/urgency first)
    profiles.sort(key=lambda p: p.scheduling_score, reverse=True)

    return {
        "station_id": station_id,
        "total_active_profiles": len(profiles),
        "profiles": profiles,
    }
