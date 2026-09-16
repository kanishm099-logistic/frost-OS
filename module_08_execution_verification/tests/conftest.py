"""
Pytest Fixtures for Module 08 Execution + Verification Intelligence.
"""

from __future__ import annotations

import pytest
from app.config.settings import Settings
from app.hal.device_manager import HALDeviceManager
from app.devices.battery import BatteryDevice
from app.devices.load import LoadDevice
from app.core.execution_engine import ExecutionEngine
from app.models.execution import ActionPlanModel, ActionItemModel, ActionTypeEnum


@pytest.fixture
def settings():
    return Settings(
        station_id="POLAR-STATION-ALPHA",
        database_url="sqlite+aiosqlite:///:memory:",
        environment="testing",
    )


@pytest.fixture
def device_manager(settings):
    mgr = HALDeviceManager(settings)
    bat = BatteryDevice("BAT-01", max_power_kw=250.0)
    load = LoadDevice("LOAD-01", max_power_kw=150.0)
    
    # Auto-connect for fixtures
    bat.is_connected = True
    load.is_connected = True

    mgr.register_adapter("BAT-01", bat)
    mgr.register_adapter("LOAD-01", load)
    return mgr


@pytest.fixture
def execution_engine(settings, device_manager):
    return ExecutionEngine(settings, device_manager)


@pytest.fixture
def sample_action_plan():
    return ActionPlanModel(
        plan_id="PLAN-TEST-001",
        station_id="POLAR-STATION-ALPHA",
        authorization_id="AUTH-TOKEN-12345",
        safety_validation_id="VAL-SAFE-777",
        status="SAFE",
        actions=[
            ActionItemModel(
                action_id="ACT-01",
                plan_id="PLAN-TEST-001",
                station_id="POLAR-STATION-ALPHA",
                action_type=ActionTypeEnum.DISCHARGE_BATTERY,
                target_id="BAT-01",
                sequence=1,
                parameters={"discharge_rate_kw": 90.0, "power_kw": 90.0},
                expected_result={"power_kw": 90.0},
            )
        ],
    )
