"""
Frost OS Module 05 — Test Fixtures & Configuration.

Shared fixtures for pytest-asyncio testing.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

os.environ["ENVIRONMENT"] = "testing"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["MOCK_MODE"] = "true"
os.environ["LOG_LEVEL"] = "WARNING"


@pytest.fixture
def settings():
    """Test settings."""
    from app.config.settings import Settings
    return Settings(
        environment="testing",
        database_url="sqlite+aiosqlite:///:memory:",
        mock_mode=True,
        log_level="WARNING",
    )


@pytest.fixture
def wind_equipment():
    """A demo wind turbine equipment."""
    from app.models.equipment import Equipment, EquipmentType, OperatingLimits
    return Equipment(
        equipment_id="WT-TEST-001",
        station_id="TEST-STATION",
        type=EquipmentType.WIND_TURBINE,
        manufacturer="TestCo",
        model="T-100",
        rated_power_kw=120.0,
        operating_limits=OperatingLimits(
            max_vibration=8.0,
            max_temperature_c=80.0,
        ),
    )


@pytest.fixture
def battery_equipment():
    """A demo battery equipment."""
    from app.models.equipment import Equipment, EquipmentType, OperatingLimits
    return Equipment(
        equipment_id="BAT-TEST-001",
        station_id="TEST-STATION",
        type=EquipmentType.BATTERY,
        manufacturer="TestCo",
        model="B-6000",
        capacity=6000.0,
        operating_limits=OperatingLimits(
            max_temperature_c=45.0,
            min_temperature_c=-20.0,
        ),
    )


@pytest.fixture
def solar_equipment():
    """A demo solar array equipment."""
    from app.models.equipment import Equipment, EquipmentType
    return Equipment(
        equipment_id="SA-TEST-001",
        station_id="TEST-STATION",
        type=EquipmentType.SOLAR_ARRAY,
        manufacturer="TestCo",
        model="S-80",
        rated_power_kw=80.0,
    )


@pytest.fixture
def normal_wind_telemetry():
    """Normal operating wind turbine telemetry batch."""
    now = datetime.now(timezone.utc)
    readings = []
    for i in range(20):
        ts = now - timedelta(seconds=(20 - i) * 5)
        wind_speed = 8.0 + np.random.normal(0, 0.5)
        power = 45.0 + np.random.normal(0, 3.0)
        readings.extend([
            {"signal_name": "wind_speed_ms", "value": wind_speed, "timestamp": ts},
            {"signal_name": "power_kw", "value": power, "timestamp": ts},
            {"signal_name": "vibration", "value": 2.0 + np.random.normal(0, 0.2), "timestamp": ts},
            {"signal_name": "rpm", "value": 150.0 + np.random.normal(0, 5), "timestamp": ts},
            {"signal_name": "nacelle_temperature_c", "value": 35.0 + np.random.normal(0, 1), "timestamp": ts},
            {"signal_name": "ambient_temperature_c", "value": -10.0 + np.random.normal(0, 0.5), "timestamp": ts},
        ])
    return readings


@pytest.fixture
def anomalous_wind_telemetry():
    """Wind turbine telemetry with icing-like anomaly."""
    now = datetime.now(timezone.utc)
    readings = []
    for i in range(20):
        ts = now - timedelta(seconds=(20 - i) * 5)
        wind_speed = 10.0 + np.random.normal(0, 0.3)
        power = 15.0 + np.random.normal(0, 2.0)  # Much lower than expected
        readings.extend([
            {"signal_name": "wind_speed_ms", "value": wind_speed, "timestamp": ts},
            {"signal_name": "power_kw", "value": power, "timestamp": ts},
            {"signal_name": "vibration", "value": 5.0 + np.random.normal(0, 0.5), "timestamp": ts},
            {"signal_name": "rpm", "value": 80.0 + np.random.normal(0, 5), "timestamp": ts},
            {"signal_name": "nacelle_temperature_c", "value": 25.0 + np.random.normal(0, 1), "timestamp": ts},
            {"signal_name": "ambient_temperature_c", "value": -15.0 + np.random.normal(0, 0.3), "timestamp": ts},
        ])
    return readings


@pytest.fixture
def normal_battery_telemetry():
    """Normal battery telemetry batch."""
    now = datetime.now(timezone.utc)
    readings = []
    for i in range(20):
        ts = now - timedelta(seconds=(20 - i) * 5)
        readings.extend([
            {"signal_name": "soc_pct", "value": 65.0 - i * 0.1, "timestamp": ts},
            {"signal_name": "soh_pct", "value": 95.0, "timestamp": ts},
            {"signal_name": "voltage_v", "value": 400.0 + np.random.normal(0, 1), "timestamp": ts},
            {"signal_name": "current_a", "value": -50.0 + np.random.normal(0, 2), "timestamp": ts},
            {"signal_name": "temperature_c", "value": 25.0 + np.random.normal(0, 0.5), "timestamp": ts},
            {"signal_name": "power_kw", "value": 20.0 + np.random.normal(0, 1), "timestamp": ts},
        ])
    return readings


@pytest.fixture
async def async_client():
    """FastAPI test client."""
    from app.main import create_app
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
