"""
Frost OS Module 03 — Test Configuration & Shared Fixtures.

Provides in-memory SQLite async database, mock Redis, client fixtures,
and domain models for unit and integration tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.energy_agent import EnergyAgent
from app.api.routes import set_engine_and_agent
from app.config.settings import Settings
from app.core.energy_engine import EnergyEngine
from app.events.publisher import EnergyEventPublisher
from app.main import create_app
from app.models.telemetry import (
    Base,
    DeviceType,
    MetricType,
    QualityStatus,
    TelemetryRecord,
)
from app.storage.database import get_session_dependency


@pytest.fixture
def settings() -> Settings:
    """Test configuration."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        mock_mode=True,
        station_id="halley_vi",
        log_level="DEBUG",
    )


@pytest_asyncio.fixture
async def db_engine():
    """Create in-memory SQLite async engine with all tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    import app.models.energy_state  # noqa: F401 Register all tables

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide transactional database session."""
    session_factory = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    mock = AsyncMock()
    mock.ping = AsyncMock(return_value=True)
    mock.xadd = AsyncMock(return_value="1234567890-0")
    return mock


@pytest.fixture
def publisher(mock_redis, settings) -> EnergyEventPublisher:
    """Energy event publisher with mock Redis."""
    return EnergyEventPublisher(mock_redis, stream_name=settings.redis_stream_energy)


@pytest.fixture
def energy_engine(settings, publisher) -> EnergyEngine:
    """EnergyEngine service instance."""
    return EnergyEngine(settings, publisher=publisher)


@pytest.fixture
def energy_agent(energy_engine) -> EnergyAgent:
    """EnergyAgent reasoning service instance."""
    return EnergyAgent(energy_engine)


@pytest.fixture
def sample_telemetry_batch() -> list[TelemetryRecord]:
    """
    Standard Antarctic station benchmark scenario:
    - Solar: 120.0 kW
    - Wind: 180.0 kW
    - Total Load: 340.0 kW (P0: 120kW, P2: 100kW, P3: 70kW, P4: 50kW)
    - Net deficit: -40.0 kW
    - Battery: SOC 72.0%, Discharging 40.0 kW, Temp -5.0°C
    - Hydrogen: 81.0% level, 300 bar
    """
    now = datetime.now(timezone.utc)
    station = "halley_vi"

    return [
        # Solar PV
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="pv_array_alpha",
            device_type=DeviceType.SOLAR,
            metric=MetricType.POWER_KW,
            value=120.0,
            unit="kW",
            quality=QualityStatus.GOOD,
            source="simulator",
        ),
        # Wind Turbines
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="wind_turbines",
            device_type=DeviceType.WIND,
            metric=MetricType.POWER_KW,
            value=180.0,
            unit="kW",
            quality=QualityStatus.GOOD,
            source="simulator",
        ),
        # Loads
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="life_support_hvac",
            device_type=DeviceType.LOAD,
            metric=MetricType.POWER_KW,
            value=120.0,
            unit="kW",
            quality=QualityStatus.GOOD,
            source="simulator",
            metadata={"priority": "CRITICAL", "tier": "P0"},
        ),
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="science_lab",
            device_type=DeviceType.LOAD,
            metric=MetricType.POWER_KW,
            value=100.0,
            unit="kW",
            quality=QualityStatus.GOOD,
            source="simulator",
            metadata={"priority": "OPERATIONAL", "tier": "P2"},
        ),
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="thermal_water_heater",
            device_type=DeviceType.LOAD,
            metric=MetricType.POWER_KW,
            value=70.0,
            unit="kW",
            quality=QualityStatus.GOOD,
            source="simulator",
            metadata={"priority": "FLEXIBLE", "tier": "P3"},
        ),
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="snow_melter",
            device_type=DeviceType.LOAD,
            metric=MetricType.POWER_KW,
            value=50.0,
            unit="kW",
            quality=QualityStatus.GOOD,
            source="simulator",
            metadata={"priority": "DEFERRABLE", "tier": "P4"},
        ),
        # Battery ESS
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="bess_container_01",
            device_type=DeviceType.BATTERY,
            metric=MetricType.SOC_PCT,
            value=72.0,
            unit="%",
            quality=QualityStatus.GOOD,
            source="simulator",
        ),
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="bess_container_01",
            device_type=DeviceType.BATTERY,
            metric=MetricType.POWER_KW,
            value=40.0,
            unit="kW",
            quality=QualityStatus.GOOD,
            source="simulator",
        ),
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="bess_container_01",
            device_type=DeviceType.BATTERY,
            metric=MetricType.TEMPERATURE_C,
            value=-5.0,
            unit="°C",
            quality=QualityStatus.GOOD,
            source="simulator",
        ),
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="bess_container_01",
            device_type=DeviceType.BATTERY,
            metric=MetricType.VOLTAGE_V,
            value=400.0,
            unit="V",
            quality=QualityStatus.GOOD,
            source="simulator",
        ),
        # Hydrogen Storage
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="h2_tank_01",
            device_type=DeviceType.HYDROGEN,
            metric=MetricType.SOC_PCT,
            value=81.0,
            unit="%",
            quality=QualityStatus.GOOD,
            source="simulator",
        ),
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="h2_tank_01",
            device_type=DeviceType.HYDROGEN,
            metric=MetricType.PRESSURE_BAR,
            value=283.5,
            unit="bar",
            quality=QualityStatus.GOOD,
            source="simulator",
        ),
        # Thermal Storage
        TelemetryRecord(
            record_id=str(uuid.uuid4()),
            timestamp=now,
            station_id=station,
            device_id="thermal_buffer_tank",
            device_type=DeviceType.THERMAL,
            metric=MetricType.TEMPERATURE_C,
            value=85.0,
            unit="°C",
            quality=QualityStatus.GOOD,
            source="simulator",
        ),
    ]


@pytest_asyncio.fixture
async def client(db_session, settings, energy_engine, energy_agent):
    """FastAPI AsyncClient fixture with in-memory database override."""
    app = create_app()

    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_get_session
    set_engine_and_agent(energy_engine, energy_agent)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
