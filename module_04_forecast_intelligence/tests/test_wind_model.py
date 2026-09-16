"""
Frost OS Module 04 — Wind Turbine Generation Model Tests.
"""

from __future__ import annotations

from app.core.model_manager import WindPowerCurveXGBoostModel
from app.core.uncertainty import UncertaintyEstimator


def test_wind_cut_in_and_cut_out_limits():
    """Verify turbine produces 0 kW below cut-in (3.0 m/s) and above cut-out (25.0 m/s)."""
    model = WindPowerCurveXGBoostModel(
        capacity_kw=120.0, cut_in_ms=3.0, rated_ms=12.0, cut_out_ms=25.0
    )

    # Below cut-in
    assert model.predict({"nwp_wind_ms": 2.8, "turbine_health": 1.0}) == 0.0
    assert model.predict({"nwp_wind_ms": 0.5, "turbine_health": 1.0}) == 0.0

    # Above cut-out (Storm feathering)
    assert model.predict({"nwp_wind_ms": 25.2, "turbine_health": 1.0}) == 0.0
    assert model.predict({"nwp_wind_ms": 32.0, "turbine_health": 1.0}) == 0.0


def test_wind_rated_power_saturation():
    """Verify turbine reaches rated capacity (120 kW) at rated speed (12 m/s)."""
    model = WindPowerCurveXGBoostModel(
        capacity_kw=120.0, cut_in_ms=3.0, rated_ms=12.0, cut_out_ms=25.0
    )
    p_rated = model.predict({"nwp_wind_ms": 12.0, "turbine_health": 1.0, "air_density_kgm3": 1.41})
    assert p_rated == 120.0

    # High wind below cut-out also caps at rated capacity
    p_high = model.predict({"nwp_wind_ms": 18.0, "turbine_health": 1.0, "air_density_kgm3": 1.41})
    assert p_high == 120.0


def test_wind_cubic_power_curve_and_density_boost():
    """Verify aerodynamic cubic growth and polar cold air density enhancement."""
    model = WindPowerCurveXGBoostModel(
        capacity_kw=120.0, cut_in_ms=3.0, rated_ms=12.0, cut_out_ms=25.0
    )

    # Intermediate speed 8 m/s
    p_cold = model.predict({"nwp_wind_ms": 8.0, "air_density_kgm3": 1.44, "turbine_health": 1.0})
    p_warm = model.predict({"nwp_wind_ms": 8.0, "air_density_kgm3": 1.22, "turbine_health": 1.0})

    assert 20.0 < p_cold < 120.0
    # Denser cold polar air generates more kinetic power
    assert p_cold > p_warm


def test_wind_turbine_icing_degradation():
    """Verify blade icing from M05 derates effective turbine capacity."""
    model = WindPowerCurveXGBoostModel(capacity_kw=120.0)
    feats_iced = {
        "nwp_wind_ms": 14.0,  # Rated speed
        "turbine_health": 0.60,  # 40% icing derating
        "air_density_kgm3": 1.41,
    }
    p_iced = model.predict(feats_iced)
    assert p_iced <= 72.0  # 120 * 0.60
