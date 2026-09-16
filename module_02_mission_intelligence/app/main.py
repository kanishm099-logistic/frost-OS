"""
Frost OS Module 02 — Main Application Entrypoint.

FastAPI application with lifespan management, structured logging,
and dependency wiring for Mission Intelligence.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.agents.mission_agent import MissionAgent
from app.api.routes import router, set_dependencies
from app.config.settings import Settings
from app.core.mission_engine import MissionEngine
from app.events.publisher import MissionEventPublisher
from app.storage.database import create_tables, dispose_engine, init_engine

# Configure structured logging
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    settings = Settings()

    # 1. Initialize Database Engine & Schema
    init_engine(settings)
    await create_tables()
    await logger.ainfo("Database initialized", db_url=settings.database_url.split("@")[-1])

    # 2. Initialize Redis Client
    redis_client = None
    if not settings.mock_mode:
        try:
            import redis.asyncio as aioredis
            redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
            await redis_client.ping()
            await logger.ainfo("Connected to Redis", redis_url=settings.redis_url)
        except Exception as e:
            await logger.awarn("Redis connection failed, running in fallback mode", error=str(e))
            redis_client = None

    # 3. Initialize Core Engines & Services
    publisher = MissionEventPublisher(redis_client, stream_name=settings.stream_missions)
    engine = MissionEngine(settings)
    agent = MissionAgent(engine)

    # Wire dependencies to API routes
    set_dependencies(settings, engine, agent, publisher)
    await logger.ainfo("Frost OS Module 02 Mission Intelligence started", port=settings.service_port)

    yield

    # Shutdown logic
    if redis_client:
        await redis_client.aclose()
    await dispose_engine()
    await logger.ainfo("Frost OS Module 02 Mission Intelligence shut down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = Settings()

    application = FastAPI(
        title="Frost OS — Module 02: Mission Intelligence",
        description=(
            "Cognitive mission and workload management layer for Frost OS. "
            "Understands workload priorities (P0-P4), energy needs (kWh), flexibility, "
            "and protective reserves."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS configuration
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(router)
    return application


app = create_app()
