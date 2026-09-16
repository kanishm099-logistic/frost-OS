"""
Frost OS Module 05 — Application Entry Point.

FastAPI application factory with lifespan management for
Diagnostic Intelligence service on port 8005.
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI

from app.agents.diagnostic_agent import DiagnosticAgent
from app.api.routes import router
from app.config.settings import get_settings
from app.core.diagnostic_engine import DiagnosticEngine
from app.events.publisher import DiagnosticEventPublisher
from app.storage.database import create_tables, dispose_engine, init_engine

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
)

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    settings = get_settings()

    await logger.ainfo(
        "diagnostic_intelligence_starting",
        station_id=settings.station_id,
        environment=settings.environment,
        port=settings.service_port,
        mock_mode=settings.mock_mode,
    )

    # Database
    init_engine(settings)
    await create_tables()

    # Redis (optional)
    redis_client = None
    if not settings.mock_mode:
        try:
            import redis.asyncio as aioredis
            redis_client = aioredis.from_url(
                settings.redis_url, decode_responses=True,
            )
            await redis_client.ping()
            await logger.ainfo("redis_connected", url=settings.redis_url)
        except Exception as e:
            await logger.awarning("redis_unavailable", error=str(e))
            redis_client = None

    # Core services
    engine = DiagnosticEngine(settings)
    publisher = DiagnosticEventPublisher(
        redis_client=redis_client,
        stream_name=settings.redis_stream_diagnostic,
    )
    agent = DiagnosticAgent(engine=engine, publisher=publisher)

    # Register demo equipment if in mock mode
    if settings.mock_mode:
        _register_demo_equipment(engine, settings)

    # Store on app state
    app.state.settings = settings
    app.state.start_time = time.time()
    app.state.diagnostic_engine = engine
    app.state.event_publisher = publisher
    app.state.diagnostic_agent = agent
    app.state.redis = redis_client

    await logger.ainfo(
        "diagnostic_intelligence_ready",
        equipment_count=len(engine.get_all_equipment_ids()),
    )

    yield

    # Shutdown
    await dispose_engine()
    if redis_client:
        await redis_client.close()
    await logger.ainfo("diagnostic_intelligence_shutdown_complete")


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()

    app = FastAPI(
        title="Frost OS — Diagnostic Intelligence (M05)",
        description=(
            "Module 05: Equipment telemetry monitoring, anomaly detection, "
            "health scoring, fault classification, and failure risk estimation "
            "for polar station infrastructure. "
            "Produces diagnostic intelligence — does NOT control hardware."
        ),
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.include_router(router, prefix="/api/v1")

    return app


def _register_demo_equipment(engine: DiagnosticEngine, settings) -> None:
    """Register demo equipment for testing/development."""
    from app.models.equipment import (
        Equipment, EquipmentType, OperatingLimits,
    )

    demo_equipment = [
        Equipment(
            equipment_id="WT-001",
            station_id=settings.station_id,
            type=EquipmentType.WIND_TURBINE,
            manufacturer="Enercon",
            model="E-33",
            rated_power_kw=120.0,
            operating_limits=OperatingLimits(
                max_vibration=8.0,
                max_temperature_c=80.0,
            ),
        ),
        Equipment(
            equipment_id="WT-002",
            station_id=settings.station_id,
            type=EquipmentType.WIND_TURBINE,
            manufacturer="Enercon",
            model="E-33",
            rated_power_kw=120.0,
            operating_limits=OperatingLimits(
                max_vibration=8.0,
                max_temperature_c=80.0,
            ),
        ),
        Equipment(
            equipment_id="SA-001",
            station_id=settings.station_id,
            type=EquipmentType.SOLAR_ARRAY,
            manufacturer="SunPower",
            model="SPR-X22-360",
            rated_power_kw=80.0,
        ),
        Equipment(
            equipment_id="BAT-001",
            station_id=settings.station_id,
            type=EquipmentType.BATTERY,
            manufacturer="Tesla",
            model="Megapack 2XL",
            capacity=6000.0,
            operating_limits=OperatingLimits(
                max_temperature_c=45.0,
                min_temperature_c=-20.0,
            ),
        ),
        Equipment(
            equipment_id="BAT-002",
            station_id=settings.station_id,
            type=EquipmentType.BATTERY,
            manufacturer="Tesla",
            model="Megapack 2XL",
            capacity=6000.0,
            operating_limits=OperatingLimits(
                max_temperature_c=45.0,
                min_temperature_c=-20.0,
            ),
        ),
        Equipment(
            equipment_id="H2-TANK-001",
            station_id=settings.station_id,
            type=EquipmentType.HYDROGEN_TANK,
            manufacturer="Linde",
            model="H2-Store-700",
            operating_limits=OperatingLimits(
                max_pressure_bar=700.0,
                min_pressure_bar=5.0,
                max_temperature_c=85.0,
            ),
        ),
        Equipment(
            equipment_id="ELY-001",
            station_id=settings.station_id,
            type=EquipmentType.ELECTROLYZER,
            manufacturer="ITM Power",
            model="HGas3SP",
            rated_power_kw=200.0,
        ),
        Equipment(
            equipment_id="FC-001",
            station_id=settings.station_id,
            type=EquipmentType.FUEL_CELL,
            manufacturer="Ballard",
            model="FCgen-HPS",
            rated_power_kw=100.0,
        ),
        Equipment(
            equipment_id="INV-001",
            station_id=settings.station_id,
            type=EquipmentType.INVERTER,
            manufacturer="SMA",
            model="Sunny Central UP",
            rated_power_kw=150.0,
        ),
        Equipment(
            equipment_id="SENS-WEATHER-001",
            station_id=settings.station_id,
            type=EquipmentType.SENSOR,
            manufacturer="Vaisala",
            model="WXT536",
        ),
    ]

    for eq in demo_equipment:
        engine.register_equipment(eq)


# Create the application instance
app = create_app()
