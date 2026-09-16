"""
Frost OS Module 02 — Test Configuration and Shared Fixtures.

Provides in-memory SQLite database, mock Redis, client fixtures,
and domain models for tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.mission_agent import MissionAgent
from app.api.routes import set_dependencies
from app.config.settings import Settings
from app.core.mission_engine import MissionEngine
from app.events.publisher import MissionEventPublisher
from app.main import create_app
from app.models.mission import (
    Base,
    Flexibility,
    Mission,
    MissionState,
    MissionType,
)
from app.models.priority import PriorityLevel


@pytest.fixture
def settings() -> Settings:
    """Test configuration."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        mock_mode=True,
        station_id="TEST-STATION-ALPHA",
        log_level="DEBUG",
    )


@pytest_asyncio.fixture
async def db_engine():
    """Create in-memory SQLite async engine."""
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
    """Provide a database session fixture."""
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
    mock.xgroup_create = AsyncMock(return_value=True)
    mock.xreadgroup = AsyncMock(return_value=[])
    mock.xack = AsyncMock(return_value=1)
    return mock


@pytest.fixture
def publisher(mock_redis, settings) -> MissionEventPublisher:
    """Event publisher fixture with mock Redis."""
    return MissionEventPublisher(mock_redis, stream_name=settings.stream_missions)


@pytest.fixture
def mission_engine(settings) -> MissionEngine:
    """MissionEngine service fixture."""
    return MissionEngine(settings)


@pytest.fixture
def mission_agent(mission_engine) -> MissionAgent:
    """MissionAgent fixture."""
    return MissionAgent(mission_engine)


@pytest.fixture
def sample_p1_mission() -> Mission:
    """Realistic P1 Ice Core Analysis mission fixture."""
    now = datetime.now(timezone.utc)
    return Mission(
        mission_id="MSN-TEST-ICECOR",
        station_id="TEST-STATION-ALPHA",
        name="Ice Core Analysis",
        description="Deep ice core spectrometry for atmospheric gas composition",
        type=MissionType.RESEARCH,
        priority=PriorityLevel.P1,
        required_power_kw=120.0,
        min_power_kw=90.0,
        max_power_kw=150.0,
        expected_duration_minutes=240,  # 4 hours
        deadline=now + timedelta(hours=18),
        flexibility=Flexibility.PARTIALLY_FLEXIBLE,
        status=MissionState.READY,
    )


@pytest.fixture
def sample_p3_mission() -> Mission:
    """Realistic P3 Computing mission fixture."""
    now = datetime.now(timezone.utc)
    return Mission(
        mission_id="MSN-TEST-COMPUT",
        station_id="TEST-STATION-ALPHA",
        name="Climate Simulation Job",
        description="Coupled atmospheric compute batch simulation",
        type=MissionType.COMPUTING,
        priority=PriorityLevel.P3,
        required_power_kw=100.0,
        min_power_kw=60.0,
        max_power_kw=120.0,
        expected_duration_minutes=180,  # 3 hours
        deadline=now + timedelta(hours=12),
        flexibility=Flexibility.FLEXIBLE,
        status=MissionState.READY,
    )


@pytest_asyncio.fixture
async def client(db_session, settings, mission_engine, mission_agent, publisher):
    """FastAPI Test Client with overridden dependencies."""
    from app.storage.database import get_session_dependency

    app = create_app()

    # Override get_session_dependency to use test db_session
    async def override_get_session():
        yield db_session

    app.dependency_overrides[get_session_dependency] = override_get_session

    # Wire module-level dependencies
    set_dependencies(settings, mission_engine, mission_agent, publisher)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
