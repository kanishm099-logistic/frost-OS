"""
Frost OS Module 01 — FastAPI Application Factory.

Wires together all components: database, Redis, module clients,
workflow engine, orchestrator, and API routes.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import redis.asyncio as redis
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import configure_routes, router, ws_manager
from app.clients.diagnostic_client import DiagnosticClient, MockDiagnosticClient
from app.clients.energy_client import EnergyClient, MockEnergyClient
from app.clients.execution_client import ExecutionClient, MockExecutionClient
from app.clients.forecast_client import ForecastClient, MockForecastClient
from app.clients.mission_client import MissionClient, MockMissionClient
from app.clients.optimizer_client import OptimizerClient, MockOptimizerClient
from app.clients.reserve_client import ReserveClient, MockReserveClient
from app.config.settings import Settings, get_settings
from app.core.decision_manager import DecisionManager
from app.core.event_router import EventRouter
from app.core.orchestrator import ModuleClients, Orchestrator
from app.core.priority_queue import PriorityEventQueue
from app.core.workflow_engine import WorkflowEngine, workflow_registry
from app.events.publisher import EventPublisher
from app.storage.database import create_tables, dispose_engine, init_engine
from app.workflows.equipment_failure import equipment_failure_workflow
from app.workflows.generation_drop import generation_drop_workflow
from app.workflows.low_reserve import low_reserve_workflow
from app.workflows.mission_start import mission_start_workflow
from app.workflows.weather_risk import weather_risk_workflow

# ── Structured Logging Setup ─────────────────────────────────────────

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Module-level references for access from routes
_redis_client: redis.Redis | None = None


def _create_clients(settings: Settings) -> ModuleClients:
    """Create module clients — mock or real based on configuration."""
    if settings.mock_mode:
        return ModuleClients(
            energy=MockEnergyClient(settings),
            forecast=MockForecastClient(settings),
            diagnostic=MockDiagnosticClient(settings),
            mission=MockMissionClient(settings),
            optimizer=MockOptimizerClient(settings),
            reserve=MockReserveClient(settings),
            execution=MockExecutionClient(settings),
        )
    else:
        return ModuleClients(
            energy=EnergyClient(settings),
            forecast=ForecastClient(settings),
            diagnostic=DiagnosticClient(settings),
            mission=MissionClient(settings),
            optimizer=OptimizerClient(settings),
            reserve=ReserveClient(settings),
            execution=ExecutionClient(settings),
        )


def _register_workflows() -> None:
    """Register all workflow handlers in the global registry."""
    workflow_registry.register("generation_drop", generation_drop_workflow)
    workflow_registry.register("mission_start", mission_start_workflow)
    workflow_registry.register("equipment_failure", equipment_failure_workflow)
    workflow_registry.register("low_reserve", low_reserve_workflow)
    workflow_registry.register("weather_risk", weather_risk_workflow)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler — startup and shutdown."""
    global _redis_client

    settings = get_settings()

    # ── Startup ──────────────────────────────────────────────────────
    logger.info("Starting Frost Orchestrator", station_id=settings.station_id, mock_mode=settings.mock_mode)

    # Initialize database
    init_engine(settings)
    await create_tables()
    logger.info("Database initialized")

    # Initialize Redis
    _redis_client = redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await _redis_client.ping()
        logger.info("Redis connected")
    except Exception as exc:
        logger.warning("Redis connection failed — continuing without streams", error=str(exc))
        _redis_client = None

    # Register workflows
    _register_workflows()
    logger.info("Workflows registered", workflows=workflow_registry.list_workflows())

    # Create components
    event_router = EventRouter()
    workflow_engine = WorkflowEngine(workflow_registry)
    decision_manager = DecisionManager(settings)
    clients = _create_clients(settings)

    publisher = EventPublisher(_redis_client) if _redis_client else None

    orchestrator = Orchestrator(
        settings=settings,
        router=event_router,
        workflow_engine=workflow_engine,
        decision_manager=decision_manager,
        clients=clients,
        publisher=publisher,
        ws_manager=ws_manager,
    )

    priority_queue = PriorityEventQueue()

    # Configure routes with dependencies
    configure_routes(orchestrator, workflow_engine, ws_manager, settings, priority_queue=priority_queue)

    logger.info("Frost Orchestrator started successfully")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────
    logger.info("Shutting down Frost Orchestrator")

    # Close module clients
    for client in [clients.energy, clients.forecast, clients.diagnostic,
                   clients.mission, clients.optimizer, clients.reserve,
                   clients.execution]:
        await client.close()

    # Close Redis
    if _redis_client:
        await _redis_client.aclose()

    # Close database
    await dispose_engine()

    logger.info("Frost Orchestrator shutdown complete")


# ── App Factory ───────────────────────────────────────────────────────

app = FastAPI(
    title="Frost OS — Module 01: Orchestrator",
    description=(
        "Event-driven coordination and decision-management layer for "
        "Frost OS, an Agentic AI Energy Operating System for remote "
        "polar research stations."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)
