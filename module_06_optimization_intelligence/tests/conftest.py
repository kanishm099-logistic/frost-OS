"""
Pytest Test Configuration & Shared Fixtures.
"""

from __future__ import annotations

import pytest

from app.config.settings import Settings
from app.models.optimization_request import OptimizationRequest, MissionPriority, ScenarioType, OptimizationMode
from app.clients.module_clients import MockSubsystemClients
from app.core.optimizer import OptimizerCore
from app.agents.optimizer_agent import OptimizerAgent


@pytest.fixture
def settings():
    """Settings fixture."""
    return Settings(
        environment="testing",
        mock_mode=True,
        database_url="sqlite+aiosqlite:///:memory:",
    )


@pytest.fixture
def optimizer_core(settings):
    """OptimizerCore fixture."""
    return OptimizerCore(settings)


@pytest.fixture
def optimizer_agent(settings):
    """OptimizerAgent fixture."""
    return OptimizerAgent(settings)


@pytest.fixture
def sample_request():
    """Standard optimization request fixture."""
    return OptimizationRequest(
        request_id="REQ-TEST-01",
        station_id="POLAR-STATION-ALPHA",
        horizon_minutes=1440,
        time_step_minutes=60,
        mode=OptimizationMode.DETERMINISTIC,
        scenario=ScenarioType.BASELINE,
        missions=MockSubsystemClients.get_mock_missions(),
        energy_state=MockSubsystemClients.get_mock_energy_state(),
        forecast=MockSubsystemClients.get_mock_forecast(24, "BASELINE"),
        equipment=MockSubsystemClients.get_mock_equipment(),
        reserve=MockSubsystemClients.get_mock_reserve(),
    )
