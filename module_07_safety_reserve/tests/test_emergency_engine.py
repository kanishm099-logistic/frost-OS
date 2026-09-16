"""
Unit tests for Emergency Detection Engine.
"""

from __future__ import annotations

from app.core.emergency_engine import EmergencyEngine


def test_thermal_overtemperature_emergency(settings, sample_energy_state, sample_equipment_health):
    engine = EmergencyEngine(settings)
    sample_energy_state["battery_temperature_c"] = 48.0  # Threshold is 45.0C

    emergency = engine.check_emergency_conditions(sample_energy_state, sample_equipment_health)
    assert emergency is not None
    assert emergency["triggered"] is True
    assert emergency["condition"] == "BATTERY_THERMAL_OVERTEMPERATURE"
    assert emergency["protective_action"] == "ISOLATE_BATTERY_SYSTEM"


def test_no_emergency_under_normal_conditions(settings, sample_energy_state, sample_equipment_health):
    engine = EmergencyEngine(settings)
    sample_energy_state["battery_temperature_c"] = 22.0
    sample_energy_state["hydrogen_pressure_bar"] = 200.0

    emergency = engine.check_emergency_conditions(sample_energy_state, sample_equipment_health)
    assert emergency is None
