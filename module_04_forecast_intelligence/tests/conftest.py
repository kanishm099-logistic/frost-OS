"""
Frost OS Module 04 — Pytest Configuration & Common Fixtures.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import AsyncGenerator

import httpx
import pandas as pd
import pytest
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config.settings import Settings, get_settings
from app.data.historical_loader import HistoricalDataLoader
from app.data.nwp_adapter import MockNWPProvider
from app.main import app
from app.storage.database import Base, get_db_session


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
async def test_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide isolated in-memory SQLite session."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def async_client(test_db_session: AsyncSession) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client connected to FastAPI app with overridden DB session."""
    async def override_get_db_session():
        yield test_db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def historical_loader() -> HistoricalDataLoader:
    return HistoricalDataLoader(
        station_id="polar-station-alpha",
        latitude=-75.58,
        longitude=-26.66,
    )


@pytest.fixture
def summer_history(historical_loader: HistoricalDataLoader) -> pd.DataFrame:
    return historical_loader.generate_synthetic_history(hours=72, season="summer")


@pytest.fixture
def winter_history(historical_loader: HistoricalDataLoader) -> pd.DataFrame:
    return historical_loader.generate_synthetic_history(hours=72, season="winter")


@pytest.fixture
def mock_nwp() -> MockNWPProvider:
    return MockNWPProvider()
