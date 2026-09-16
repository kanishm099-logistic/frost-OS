"""
Frost OS Module 04 — Station Load Forecasting Tests.
"""

from __future__ import annotations

from app.core.model_manager import StationLoadGradientBoostingModel


def test_load_baseline_and_heating_sensitivity():
    """Verify load increases with colder outdoor ambient temperatures."""
    model = StationLoadGradientBoostingModel(base_load_kw=35.0, heating_coeff=0.85)

    load_mild = model.predict({"nwp_temp_c": 0.0, "mission_total_kw": 0.0, "hour_sin": 0.0})
    load_cold = model.predict({"nwp_temp_c": -30.0, "mission_total_kw": 0.0, "hour_sin": 0.0})

    assert load_mild >= 35.0
    # At -30°C: heating adds ~ (18 - (-30)) * 0.85 ~ 40.8 kW -> total ~ 75.8 kW
    assert load_cold > load_mild + 20.0


def test_load_with_active_missions():
    """Verify demand scales with concurrent research missions from Module 02."""
    model = StationLoadGradientBoostingModel(base_load_kw=35.0)

    load_idle = model.predict({"nwp_temp_c": -15.0, "mission_total_kw": 0.0, "hour_sin": 0.0})
    load_with_mission = model.predict({"nwp_temp_c": -15.0, "mission_total_kw": 25.0, "hour_sin": 0.0})

    assert load_with_mission >= load_idle + 24.0


def test_load_physical_bounds():
    """Verify station load never drops below life support minimum (15 kW)."""
    model = StationLoadGradientBoostingModel(base_load_kw=35.0)
    p = model.predict({"nwp_temp_c": 25.0, "mission_total_kw": 0.0, "hour_sin": -1.0})
    assert p >= 15.0
