"""
Frost OS Module 08 — FastAPI Application Factory.

Wires database initialization, Redis event streaming, API routes, HAL Device Manager, and Execution Engine.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import redis.asyncio as redis
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config.settings import get_settings
from app.storage.repository import init_engine, create_tables, dispose_engine

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

_redis_client: redis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan handler for startup and shutdown."""
    global _redis_client
    settings = get_settings()

    logger.info("Starting Frost OS Module 08 Execution + Verification Intelligence", station_id=settings.station_id)

    # Initialize DB
    init_engine(settings)
    await create_tables()
    logger.info("Database initialized successfully")

    # Initialize Redis connection
    _redis_client = redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await _redis_client.ping()
        logger.info("Redis connected successfully")
    except Exception as exc:
        logger.warning("Redis connection unavailable — running without event streaming", error=str(exc))
        _redis_client = None

    yield

    logger.info("Shutting down Frost OS Module 08")
    if _redis_client:
        await _redis_client.aclose()
    await dispose_engine()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Frost OS — Module 08: Execution + Verification Intelligence",
    description=(
        "Controlled actuator gateway layer for remote polar research station microgrids. "
        "Translates authorized high-level action plans into protocol commands (Modbus, OPC-UA, CAN, MQTT), "
        "executes commands through Hardware Abstraction Layer, and verifies telemetry against expected setpoints."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
