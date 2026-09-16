"""
Frost OS Module 04 — Solar PV Generation Model Tests.
"""

from __future__ import annotations

from app.core.model_manager import SolarPhysicalXGBoostModel
from app.core.uncertainty import UncertaintyEstimator
from app.models.forecast import DataQuality


def test_solar_zero_elevation_produces_zero_power():
    """Verify that sun below or at horizon strictly produces 0.0 kW without false certainty."""
    model = SolarPhysicalXGBoostModel(capacity_kw=80.0)

    # Elevation 0.0 or negative
    assert model.predict({"solar_elevation_deg": 0.0, "nwp_cloud_pct": 10.0}) == 0.0
    assert model.predict({"solar_elevation_deg": -5.5, "nwp_cloud_pct": 0.0}) == 0.0


def test_solar_polar_day_generation():
    """Verify solar power generated during positive elevation polar day."""
    model = SolarPhysicalXGBoostModel(capacity_kw=80.0, panel_area_m2=420.0)

    # Clean sun at 25 degrees elevation, 20% cloud
    feats = {
        "solar_elevation_deg": 25.0,
        "nwp_cloud_pct": 20.0,
        "nwp_temp_c": -15.0,
        "pv_health": 1.0,
    }
    p = model.predict(feats)
    assert 20.0 < p <= 80.0

    # High overcast cloud attenuates generation
    feats_cloudy = {**feats, "nwp_cloud_pct": 95.0}
    p_cloudy = model.predict(feats_cloudy)
    assert p_cloudy < p


def test_solar_capacity_clamping_and_intervals():
    """Verify physical maximum capacity constraint and non-negative prediction intervals."""
    model = SolarPhysicalXGBoostModel(capacity_kw=80.0)
    unc = UncertaintyEstimator()

    # Even extreme irradiance feature cannot exceed 80 kW
    feats_extreme = {
        "solar_elevation_deg": 45.0,
        "nwp_cloud_pct": 0.0,
        "nwp_temp_c": -40.0,
        "pv_health": 1.0,
    }
    pred = model.predict(feats_extreme)
    assert pred <= 80.0

    # Uncertainty interval
    interval = unc.estimate_interval(
        point_prediction=pred,
        lead_time_hours=6.0,
        base_residual_std=4.5,
        physical_min=0.0,
        physical_max=80.0,
    )
    assert interval.lower_bound >= 0.0
    assert interval.upper_bound <= 80.0
    assert interval.lower_bound <= interval.prediction <= interval.upper_bound


def test_solar_pv_health_derating():
    """Verify Module 05 equipment degradation signal reduces power accordingly."""
    model = SolarPhysicalXGBoostModel(capacity_kw=80.0)
    feats_healthy = {"solar_elevation_deg": 20.0, "nwp_cloud_pct": 10.0, "pv_health": 1.0}
    feats_derated = {"solar_elevation_deg": 20.0, "nwp_cloud_pct": 10.0, "pv_health": 0.5}

    p_healthy = model.predict(feats_healthy)
    p_derated = model.predict(feats_derated)
    assert round(p_derated, 1) == round(p_healthy * 0.5, 1)
