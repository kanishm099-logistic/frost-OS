"""
Frost OS Module 01 — Test Configuration & Shared Fixtures.

Provides test client, mock database session, mock Redis,
mock module clients, and event factories for all test files.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.settings import Settings
from app.models.event import Base, EventType, Severity, StationEvent
from app.models.decision import DecisionContext, DecisionStatus, ModuleResponse
from app.models.action_plan import ActionPlan, PlanStatus, SafetyStatus, PlannedAction
from app.core.event_router import EventRouter
from app.core.workflow_engine import WorkflowEngine, WorkflowRegistry
from app.core.decision_manager import DecisionManager
from app.clients.mission_client import MockMissionClient
from app.clients.energy_client import MockEnergyClient
from app.clients.forecast_client import MockForecastClient
from app.clients.diagnostic_client import MockDiagnosticClient
from app.clients.optimizer_client import MockOptimizerClient
from app.clients.reserve_client import MockReserveClient
from app.clients.execution_client import MockExecutionClient
from app.core.orchestrator import ModuleClients, Orchestrator
from app.events.publisher import EventPublisher


# ── Pytest Configuration ──────────────────────────────────────────────


# ── Settings ──────────────────────────────────────────────────────────

@pytest.fixture
def settings() -> Settings:
    """Test settings with mock mode enabled."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        mock_mode=True,
        station_id="TEST-STATION-01",
        log_level="DEBUG",
        client_timeout_seconds=5.0,
        client_max_retries=1,
        circuit_breaker_failure_threshold=3,
        circuit_breaker_recovery_timeout=1.0,
    )


# ── Database ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a test database session."""
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


# ── Mock Redis ────────────────────────────────────────────────────────

@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    redis_mock = AsyncMock()
    redis_mock.ping = AsyncMock(return_value=True)
    redis_mock.sismember = AsyncMock(return_value=False)
    redis_mock.sadd = AsyncMock()
    redis_mock.expire = AsyncMock()
    redis_mock.xadd = AsyncMock(return_value="1234567890-0")
    return redis_mock


# ── Mock Clients ──────────────────────────────────────────────────────

@pytest.fixture
def mock_clients(settings) -> ModuleClients:
    """Create mock module clients for testing."""
    return ModuleClients(
        energy=MockEnergyClient(settings),
        forecast=MockForecastClient(settings),
        diagnostic=MockDiagnosticClient(settings),
        mission=MockMissionClient(settings),
        optimizer=MockOptimizerClient(settings),
        reserve=MockReserveClient(settings),
        execution=MockExecutionClient(settings),
    )


# ── Core Components ──────────────────────────────────────────────────

@pytest.fixture
def event_router() -> EventRouter:
    """Create an event router."""
    return EventRouter()


@pytest.fixture
def workflow_registry() -> WorkflowRegistry:
    """Create a fresh workflow registry."""
    return WorkflowRegistry()


@pytest.fixture
def workflow_engine(workflow_registry) -> WorkflowEngine:
    """Create a workflow engine with empty registry."""
    return WorkflowEngine(workflow_registry)


@pytest.fixture
def decision_manager(settings) -> DecisionManager:
    """Create a decision manager."""
    return DecisionManager(settings)


@pytest.fixture
def mock_publisher(mock_redis) -> EventPublisher:
    """Create a mock event publisher."""
    return EventPublisher(mock_redis)


@pytest.fixture
def orchestrator(settings, event_router, mock_clients, mock_publisher) -> Orchestrator:
    """Create an orchestrator with full mock workflow engine."""
    from app.workflows.generation_drop import generation_drop_workflow
    from app.workflows.mission_start import mission_start_workflow
    from app.workflows.equipment_failure import equipment_failure_workflow
    from app.workflows.low_reserve import low_reserve_workflow
    from app.workflows.weather_risk import weather_risk_workflow

    registry = WorkflowRegistry()
    registry.register("generation_drop", generation_drop_workflow)
    registry.register("mission_start", mission_start_workflow)
    registry.register("equipment_failure", equipment_failure_workflow)
    registry.register("low_reserve", low_reserve_workflow)
    registry.register("weather_risk", weather_risk_workflow)

    engine = WorkflowEngine(registry)
    dm = DecisionManager(settings)

    return Orchestrator(
        settings=settings,
        router=event_router,
        workflow_engine=engine,
        decision_manager=dm,
        clients=mock_clients,
        publisher=mock_publisher,
    )


# ── Event Factories ──────────────────────────────────────────────────

@pytest.fixture
def wind_drop_event() -> StationEvent:
    """Create a WIND_POWER_DROP test event (180 → 70 kW)."""
    return StationEvent(
        source="wind-sensor-array-01",
        event_type=EventType.WIND_POWER_DROP,
        severity=Severity.HIGH,
        station_id="TEST-STATION-01",
        payload={
            "previous_kw": 180.0,
            "current_kw": 70.0,
            "drop_pct": 61.1,
            "turbine_id": "WIND-TURBINE-01",
        },
    )


@pytest.fixture
def battery_low_event() -> StationEvent:
    """Create a BATTERY_LOW test event."""
    return StationEvent(
        source="battery-monitor-01",
        event_type=EventType.BATTERY_LOW,
        severity=Severity.HIGH,
        station_id="TEST-STATION-01",
        payload={
            "current_soc_pct": 18.0,
            "threshold_pct": 20.0,
            "battery_kwh": 108.0,
            "capacity_kwh": 600.0,
        },
    )


@pytest.fixture
def mission_started_event() -> StationEvent:
    """Create a MISSION_STARTED test event."""
    return StationEvent(
        source="mission-control",
        event_type=EventType.MISSION_STARTED,
        severity=Severity.LOW,
        station_id="TEST-STATION-01",
        payload={
            "mission_id": "MSN-004",
            "name": "Emergency Sample Analysis",
            "priority": "P1",
            "power_requirement_kw": 30.0,
        },
    )


@pytest.fixture
def equipment_degraded_event() -> StationEvent:
    """Create an EQUIPMENT_DEGRADED test event."""
    return StationEvent(
        source="diagnostic-system",
        event_type=EventType.EQUIPMENT_DEGRADED,
        severity=Severity.HIGH,
        station_id="TEST-STATION-01",
        payload={
            "equipment_id": "SOLAR-PANEL-ARRAY-02",
            "equipment_type": "solar_panel",
            "degradation_pct": 45.0,
        },
    )


@pytest.fixture
def weather_warning_event() -> StationEvent:
    """Create a WEATHER_WARNING test event."""
    return StationEvent(
        source="weather-station",
        event_type=EventType.WEATHER_WARNING,
        severity=Severity.MEDIUM,
        station_id="TEST-STATION-01",
        payload={
            "warning_type": "blizzard",
            "expected_wind_speed_ms": 25.0,
            "expected_temperature_c": -45.0,
            "onset_hours": 6,
        },
    )
