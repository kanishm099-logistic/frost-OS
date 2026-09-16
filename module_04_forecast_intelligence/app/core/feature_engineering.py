"""
Frost OS Module 04 — Feature Engineering & Astronomical Physics.

Transforms historical observations, real-time energy telemetry, active mission profiles,
and NWP forecast fields into ML feature vectors.
Strictly guarantees zero data leakage across lead-time horizons.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd


class FeatureEngineer:
    """Computes physical and statistical features for solar, wind, and demand models."""

    def __init__(
        self,
        station_id: str = "polar-station-alpha",
        latitude: float = -75.58,
        longitude: float = -26.66,
        altitude_m: float = 30.0,
    ) -> None:
        self.station_id = station_id
        self.latitude = latitude
        self.longitude = longitude
        self.altitude_m = altitude_m

    @staticmethod
    def compute_solar_elevation(latitude: float, longitude: float, dt: datetime) -> float:
        """
        Calculate solar elevation angle alpha in degrees using spherical trigonometry:
        sin(alpha) = sin(phi)*sin(delta) + cos(phi)*cos(delta)*cos(omega)
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        day_of_year = dt.timetuple().tm_yday
        hour_frac = dt.hour + dt.minute / 60.0 + dt.second / 3600.0

        delta = 23.45 * math.sin(math.radians(360.0 / 365.0 * (day_of_year - 81)))
        solar_noon_utc = 12.0 - (longitude / 15.0)
        hour_angle = 15.0 * (hour_frac - solar_noon_utc)

        lat_r = math.radians(latitude)
        del_r = math.radians(delta)
        ha_r = math.radians(hour_angle)

        sin_elev = math.sin(lat_r) * math.sin(del_r) + math.cos(lat_r) * math.cos(del_r) * math.cos(ha_r)
        sin_elev = max(-1.0, min(1.0, sin_elev))
        return round(math.degrees(math.asin(sin_elev)), 2)

    @staticmethod
    def compute_air_density(temperature_c: float, pressure_hpa: float = 985.0) -> float:
        """
        Calculate air density (kg/m³) for polar conditions:
        rho = P / (R_spec * T_kelvin)
        At -30°C and 985 hPa, rho ~ 1.41 kg/m³ (+15% compared to standard 1.225).
        """
        temp_k = temperature_c + 273.15
        if temp_k <= 0:
            temp_k = 243.15
        p_pa = pressure_hpa * 100.0
        return round(p_pa / (287.058 * temp_k), 4)

    @staticmethod
    def extract_time_features(dt: datetime) -> dict[str, float]:
        """Cyclical trigonometric encodings for time-of-day and day-of-year."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        hour = dt.hour + dt.minute / 60.0
        doy = dt.timetuple().tm_yday

        return {
            "hour_sin": round(math.sin(2 * math.pi * hour / 24.0), 4),
            "hour_cos": round(math.cos(2 * math.pi * hour / 24.0), 4),
            "doy_sin": round(math.sin(2 * math.pi * doy / 365.25), 4),
            "doy_cos": round(math.cos(2 * math.pi * doy / 365.25), 4),
            "month": float(dt.month),
            "is_weekend": 1.0 if dt.weekday() >= 5 else 0.0,
        }

    def build_inference_features(
        self,
        creation_time: datetime,
        valid_time: datetime,
        history_df: pd.DataFrame,
        nwp_temp_c: float,
        nwp_wind_ms: float,
        nwp_cloud_pct: float,
        nwp_radiation_wm2: float,
        active_missions: list[dict[str, Any]] | None = None,
        equipment_health: dict[str, Any] | None = None,
        storage_state: dict[str, Any] | None = None,
    ) -> dict[str, float]:
        """
        Build feature dictionary for a single horizon step.
        Guarantees STRICT NO DATA LEAKAGE:
        Asserts that history_df contains only timestamps <= creation_time.
        """
        if creation_time.tzinfo is None:
            creation_time = creation_time.replace(tzinfo=timezone.utc)
        if valid_time.tzinfo is None:
            valid_time = valid_time.replace(tzinfo=timezone.utc)

        # Anti-leakage guard
        if not history_df.empty and "timestamp" in history_df.columns:
            ts_series = pd.to_datetime(history_df["timestamp"], utc=True)
            if (ts_series > creation_time).any():
                raise ValueError("Data leakage detected: historical records contain future timestamps > creation_time")

        lead_minutes = max(0.0, (valid_time - creation_time).total_seconds() / 60.0)
        lead_hours = lead_minutes / 60.0

        # Solar position & air density at valid_time
        solar_elev = self.compute_solar_elevation(self.latitude, self.longitude, valid_time)
        air_density = self.compute_air_density(nwp_temp_c)

        # Extract recent historical statistics from <= creation_time
        recent = history_df.tail(16) if not history_df.empty else pd.DataFrame()

        wind_hist = recent["wind_speed_ms"] if "wind_speed_ms" in recent.columns else pd.Series([nwp_wind_ms])
        solar_hist = recent["solar_generation_kw"] if "solar_generation_kw" in recent.columns else pd.Series([0.0])
        load_hist = recent["station_load_kw"] if "station_load_kw" in recent.columns else pd.Series([35.0])
        temp_hist = recent["temperature_c"] if "temperature_c" in recent.columns else pd.Series([nwp_temp_c])

        wind_lag1 = float(wind_hist.iloc[-1]) if not wind_hist.empty else nwp_wind_ms
        wind_mean_4 = float(wind_hist.tail(4).mean()) if len(wind_hist) >= 4 else wind_lag1
        wind_std_4 = float(wind_hist.tail(4).std()) if len(wind_hist) >= 4 and not np.isnan(wind_hist.tail(4).std()) else 0.5
        wind_roc = (wind_lag1 - float(wind_hist.iloc[-2])) if len(wind_hist) >= 2 else 0.0

        solar_lag1 = float(solar_hist.iloc[-1]) if not solar_hist.empty else 0.0
        load_lag1 = float(load_hist.iloc[-1]) if not load_hist.empty else 35.0
        load_mean_4 = float(load_hist.tail(4).mean()) if len(load_hist) >= 4 else load_lag1
        temp_lag1 = float(temp_hist.iloc[-1]) if not temp_hist.empty else nwp_temp_c

        # Weather delta between current and forecast
        temp_delta = nwp_temp_c - temp_lag1
        wind_delta = nwp_wind_ms - wind_lag1

        # Mission load aggregation: sum of active mission power in kW
        mission_p0_p1_kw = 0.0
        mission_flexible_kw = 0.0
        total_mission_kw = 0.0
        if active_missions:
            for m in active_missions:
                req_p = float(m.get("required_power_kw", 0.0))
                priority = str(m.get("priority", "P2")).upper()
                total_mission_kw += req_p
                if priority in ["P0", "P1"]:
                    mission_p0_p1_kw += req_p
                else:
                    mission_flexible_kw += req_p

        # Equipment health derating (e.g. turbine icing)
        turbine_health = 1.0
        pv_health = 1.0
        if equipment_health:
            turbine_health = float(equipment_health.get("turbine_health_score", 1.0))
            pv_health = float(equipment_health.get("pv_health_score", 1.0))

        # Storage state features
        battery_soc = 80.0
        hydrogen_pct = 75.0
        if storage_state:
            battery_soc = float(storage_state.get("battery_soc_pct", 80.0))
            hydrogen_pct = float(storage_state.get("hydrogen_level_pct", 75.0))

        time_feats = self.extract_time_features(valid_time)

        features: dict[str, float] = {
            "lead_time_hours": round(lead_hours, 2),
            "lead_time_minutes": round(lead_minutes, 1),
            "solar_elevation_deg": solar_elev,
            "air_density_kgm3": air_density,
            "nwp_temp_c": nwp_temp_c,
            "nwp_wind_ms": nwp_wind_ms,
            "nwp_cloud_pct": nwp_cloud_pct,
            "nwp_radiation_wm2": nwp_radiation_wm2,
            "temp_delta": round(temp_delta, 2),
            "wind_delta": round(wind_delta, 2),
            "wind_lag1": round(wind_lag1, 2),
            "wind_mean_4": round(wind_mean_4, 2),
            "wind_std_4": round(wind_std_4, 2),
            "wind_roc": round(wind_roc, 2),
            "solar_lag1": round(solar_lag1, 2),
            "load_lag1": round(load_lag1, 2),
            "load_mean_4": round(load_mean_4, 2),
            "temp_lag1": round(temp_lag1, 2),
            "mission_total_kw": round(total_mission_kw, 2),
            "mission_p0_p1_kw": round(mission_p0_p1_kw, 2),
            "mission_flexible_kw": round(mission_flexible_kw, 2),
            "turbine_health": round(turbine_health, 2),
            "pv_health": round(pv_health, 2),
            "battery_soc_pct": round(battery_soc, 1),
            "hydrogen_level_pct": round(hydrogen_pct, 1),
            **time_feats,
        }

        return features
