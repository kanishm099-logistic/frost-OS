"""
Unit tests for Dynamic Reserve Engine.
"""

from __future__ import annotations

from app.core.reserve_engine import ReserveEngine


def test_reserve_calculation_structure(settings, sample_energy_state, sample_missions, sample_forecast, sample_equipment_health):
    engine = ReserveEngine(settings)
    calc = engine.calculate_reserve(
        energy_state=sample_energy_state,
        missions=sample_missions,
        forecast=sample_forecast,
        equipment_health=sample_equipment_health,
    )

    assert calc.station_id == "POLAR-STATION-ALPHA"
    assert calc.station_reserve_kwh > 0
    assert calc.emergency_reserve_kwh > 0
    assert calc.total_protected_reserve_kwh > 0
    assert len(calc.components) >= 5
    assert isinstance(calc.reserve_satisfied, bool)


def test_storm_multiplier_increases_reserve(settings, sample_energy_state, sample_missions, sample_forecast, sample_equipment_health):
    engine = ReserveEngine(settings)
    normal_calc = engine.calculate_reserve(
        energy_state=sample_energy_state,
        missions=sample_missions,
        forecast=sample_forecast,
        equipment_health=sample_equipment_health,
        weather_event="NORMAL",
    )

    storm_calc = engine.calculate_reserve(
        energy_state=sample_energy_state,
        missions=sample_missions,
        forecast=sample_forecast,
        equipment_health=sample_equipment_health,
        weather_event="STORM",
    )

    assert storm_calc.total_protected_reserve_kwh > normal_calc.total_protected_reserve_kwh
