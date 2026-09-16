"""
Frost OS Module 04 — Feature Engineering & Anti-Leakage Tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.core.feature_engineering import FeatureEngineer


def test_anti_leakage_guard():
    """Verify that feature engineering strictly raises ValueError if history contains future timestamps."""
    fe = FeatureEngineer(latitude=-75.58, longitude=-26.66)
    creation_time = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    valid_time = creation_time + timedelta(hours=6)

    # Corrupt history with future timestamp (1 hour after creation_time)
    future_history = pd.DataFrame([
        {"timestamp": creation_time - timedelta(hours=2), "wind_speed_ms": 10.0, "station_load_kw": 35.0},
        {"timestamp": creation_time + timedelta(hours=1), "wind_speed_ms": 12.0, "station_load_kw": 40.0},
    ])

    with pytest.raises(ValueError, match="Data leakage detected"):
        fe.build_inference_features(
            creation_time=creation_time,
            valid_time=valid_time,
            history_df=future_history,
            nwp_temp_c=-20.0,
            nwp_wind_ms=10.0,
            nwp_cloud_pct=30.0,
            nwp_radiation_wm2=150.0,
        )


def test_solar_elevation_polar_summer_and_winter():
    """Verify continuous positive elevation in austral summer and negative in winter."""
    fe = FeatureEngineer(latitude=-75.58, longitude=-26.66)

    # Austral summer solstice: Dec 21
    summer_noon = datetime(2026, 12, 21, 14, 0, tzinfo=timezone.utc)
    elev_summer_noon = fe.compute_solar_elevation(-75.58, -26.66, summer_noon)
    assert elev_summer_noon > 30.0  # High sun at polar summer noon

    summer_midnight = datetime(2026, 12, 21, 2, 0, tzinfo=timezone.utc)
    elev_summer_midnight = fe.compute_solar_elevation(-75.58, -26.66, summer_midnight)
    assert elev_summer_midnight > 5.0  # Still above horizon during polar day midnight sun

    # Austral winter solstice: June 21
    winter_noon = datetime(2026, 6, 21, 14, 0, tzinfo=timezone.utc)
    elev_winter_noon = fe.compute_solar_elevation(-75.58, -26.66, winter_noon)
    assert elev_winter_noon < 0.0  # Sun remains below horizon 24h a day


def test_cold_air_density_calculation():
    """Verify polar cold air density boost compared to standard sea-level density (1.225 kg/m³)."""
    # At -30°C, 985 hPa: rho = 98500 / (287.058 * 243.15) ~ 1.411 kg/m³
    rho_cold = FeatureEngineer.compute_air_density(temperature_c=-30.0, pressure_hpa=985.0)
    assert 1.38 < rho_cold < 1.45

    # At 0°C, 985 hPa: rho ~ 1.256 kg/m³
    rho_warm = FeatureEngineer.compute_air_density(temperature_c=0.0, pressure_hpa=985.0)
    assert rho_cold > rho_warm


def test_time_and_mission_features(summer_history: pd.DataFrame):
    """Verify cyclical time encodings and mission load power summation."""
    fe = FeatureEngineer(latitude=-75.58, longitude=-26.66)
    now = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    valid = now + timedelta(hours=2)

    # Filter history strictly to <= now
    hist = summer_history[summer_history["timestamp"] <= now]

    active_missions = [
        {"name": "Life Support", "priority": "P0", "required_power_kw": 18.0},
        {"name": "Ice Core Drill", "priority": "P2", "required_power_kw": 12.5},
        {"name": "EV Battery Fast Charge", "priority": "P3", "required_power_kw": 8.0},
    ]
    eq_health = {"turbine_health_score": 0.85, "pv_health_score": 0.95}

    feats = fe.build_inference_features(
        creation_time=now,
        valid_time=valid,
        history_df=hist,
        nwp_temp_c=-15.0,
        nwp_wind_ms=11.2,
        nwp_cloud_pct=40.0,
        nwp_radiation_wm2=300.0,
        active_missions=active_missions,
        equipment_health=eq_health,
    )

    assert feats["mission_total_kw"] == 38.5
    assert feats["mission_p0_p1_kw"] == 18.0
    assert feats["mission_flexible_kw"] == 20.5
    assert feats["turbine_health"] == 0.85
    assert feats["pv_health"] == 0.95
    assert -1.0 <= feats["hour_sin"] <= 1.0
    assert feats["lead_time_hours"] == 2.0
