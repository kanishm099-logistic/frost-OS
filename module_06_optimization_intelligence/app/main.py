"""
Frost OS Module 06 — FastAPI Application Factory.

Wires together database initialization, Redis event streaming, API routes,
and the Optimizer Agent.
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

# Structured Logging Setup
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
    """Application lifespan handler — startup and shutdown."""
    global _redis_client

    settings = get_settings()

    logger.info("Starting Frost OS Module 06 Optimization Intelligence", station_id=settings.station_id)

    # Initialize Database
    init_engine(settings)
    await create_tables()
    logger.info("Database initialized successfully")

    # Initialize Redis
    _redis_client = redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await _redis_client.ping()
        logger.info("Redis connected successfully")
    except Exception as exc:
        logger.warning("Redis connection unavailable — running without streams", error=str(exc))
        _redis_client = None

    yield

    logger.info("Shutting down Frost OS Module 06")
    if _redis_client:
        await _redis_client.aclose()
    await dispose_engine()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Frost OS — Module 06: Optimization Intelligence",
    description=(
        "Mathematical energy optimization decision engine for remote polar research stations. "
        "Formulates MILP energy allocation across missions, battery storage, and hydrogen reserves "
        "without bypassing Module 07 Safety boundaries."
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

from pathlib import Path
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

app.include_router(router)

# Mount Dashboard static files directly from the repository
dashboard_dir = Path(__file__).resolve().parent.parent.parent / "dashboard"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

    @app.get("/", include_in_schema=False)
    async def root_to_dashboard():
        """Redirect root URL directly to the mission control dashboard."""
        return RedirectResponse(url="/dashboard/")

