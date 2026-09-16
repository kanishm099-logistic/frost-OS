"""
Pytest Fixtures for Module 07 Safety + Reserve Intelligence.
"""

from __future__ import annotations

import pytest
from app.config.settings import Settings
from app.core.safety_engine import SafetyEngine


@pytest.fixture
def settings():
    return Settings(
        station_id="POLAR-STATION-ALPHA",
        database_url="sqlite+aiosqlite:///:memory:",
        environment="testing",
    )


@pytest.fixture
def safety_engine(settings):
    return SafetyEngine(settings)


@pytest.fixture
def sample_energy_state():
    return {
        "battery_soc_pct": 60.0,
        "battery_energy_kwh": 480.0,
        "battery_capacity_kwh": 800.0,
        "hydrogen_energy_kwh": 200.0,
        "hydrogen_level_pct": 65.0,
        "current_generation_kw": 80.0,
        "current_load_kw": 60.0,
        "critical_load_kw": 40.0,
        "battery_temperature_c": 22.0,
        "hydrogen_pressure_bar": 200.0,
        "max_battery_discharge_kw": 100.0,
        "data_quality": "GOOD",
    }


@pytest.fixture
def sample_missions():
    return [
        {
            "mission_id": "MIS-P0-LIFE",
            "mission_name": "Life Support",
            "priority": "P0",
            "power_requirement_kw": 40.0,
            "min_power_kw": 40.0,
            "duration_hours": 24.0,
            "critical": True,
        },
        {
            "mission_id": "MIS-P1-ICE",
            "mission_name": "Deep Ice Core Drilling",
            "priority": "P1",
            "power_requirement_kw": 90.0,
            "min_power_kw": 90.0,
            "duration_hours": 8.0,
            "critical": True,
        },
    ]


@pytest.fixture
def sample_forecast():
    return {
        "confidence": 0.85,
        "shortage_probability": 0.05,
        "solar_kw": 25.0,
        "wind_kw": 55.0,
    }


@pytest.fixture
def sample_equipment_health():
    return {
        "overall_health_score": 90.0,
        "equipment": {
            "TURBINE-01": {"status": "HEALTHY", "derating_factor": 1.0},
            "BATTERY-BANK": {"status": "HEALTHY", "derating_factor": 1.0},
        },
    }


@pytest.fixture
def sample_proposed_plan():
    return {
        "optimization_id": "OPT-TEST-001",
        "total_load_kw": 130.0,
        "actions": [
            {"action_type": "MAINTAIN_DISPATCH", "target": "Microgrid"},
        ],
        "mission_allocations": [
            {
                "mission_id": "MIS-P0-LIFE",
                "mission_name": "Life Support",
                "priority": "P0",
                "requested_power_kw": 40.0,
                "allocated_power_kw": 40.0,
                "min_power_kw": 40.0,
                "satisfied": True,
            },
            {
                "mission_id": "MIS-P1-ICE",
                "mission_name": "Deep Ice Core Drilling",
                "priority": "P1",
                "requested_power_kw": 90.0,
                "allocated_power_kw": 90.0,
                "min_power_kw": 90.0,
                "satisfied": True,
            },
        ],
        "storage_schedule": [
            {"time_step": 0, "battery_charge_kw": 0.0, "battery_discharge_kw": 50.0, "battery_soc": 60.0},
        ],
    }
