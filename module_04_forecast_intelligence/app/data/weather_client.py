"""
Frost OS Module 04 — Weather Client & Ingestion Layer.

Manages real-time meteorological observations, data freshness verification,
and polar atmospheric indices (icing risk, blizzard classification).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.models.weather import PolarWeatherConditions, WeatherCondition, WeatherObservation

logger = structlog.get_logger(__name__)


class WeatherClient:
    """Client for local station weather station sensors and recent telemetry buffer."""

    def __init__(self, station_id: str, latitude: float, longitude: float) -> None:
        self.station_id = station_id
        self.latitude = latitude
        self.longitude = longitude
        self._cache: list[WeatherObservation] = []

    def add_observation(self, obs: WeatherObservation) -> None:
        """Store new observation in sliding 72-hour memory buffer."""
        self._cache.append(obs)
        # Keep latest 72 hours (up to ~4320 minutes)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
        self._cache = [o for o in self._cache if o.timestamp >= cutoff]

    def get_latest_observation(self) -> WeatherObservation:
        """Return the most recent observation or synthesize a nominal baseline."""
        if self._cache:
            return self._cache[-1]
        # Return fallback observation if none ingested yet
        now = datetime.now(timezone.utc)
        return WeatherObservation(
            station_id=self.station_id,
            timestamp=now,
            temperature_c=-22.0,
            pressure_hpa=985.0,
            wind_speed_ms=8.5,
            wind_direction_deg=220.0,
            wind_gust_ms=12.0,
            cloud_cover_pct=35.0,
            global_horizontal_irradiance_wm2=120.0,
            direct_normal_irradiance_wm2=250.0,
            diffuse_horizontal_irradiance_wm2=40.0,
            relative_humidity_pct=80.0,
            visibility_km=15.0,
            condition=WeatherCondition.PARTLY_CLOUDY,
            source="synthetic_init",
        )

    def get_history(self, hours: int = 24) -> list[WeatherObservation]:
        """Return observations within the past N hours."""
        if not self._cache:
            return [self.get_latest_observation()]
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        res = [o for o in self._cache if o.timestamp >= cutoff]
        return res if res else [self._cache[-1]]

    def compute_polar_conditions(self, obs: WeatherObservation | None = None) -> PolarWeatherConditions:
        """Derive astronomical solar elevation, polar day/night flags, and icing risks."""
        target = obs or self.get_latest_observation()
        dt = target.timestamp

        day_of_year = dt.timetuple().tm_yday
        hour_frac = dt.hour + dt.minute / 60.0 + dt.second / 3600.0

        # Solar declination approximation (Cooper 1969)
        delta = 23.45 * math.sin(math.radians(360.0 / 365.0 * (day_of_year - 81)))
        # Hour angle: 15 degrees per hour from solar noon (UTC + lon/15)
        solar_noon_utc = 12.0 - (self.longitude / 15.0)
        hour_angle = 15.0 * (hour_frac - solar_noon_utc)

        # Solar elevation angle alpha
        lat_rad = math.radians(self.latitude)
        delta_rad = math.radians(delta)
        ha_rad = math.radians(hour_angle)

        sin_elev = math.sin(lat_rad) * math.sin(delta_rad) + math.cos(lat_rad) * math.cos(delta_rad) * math.cos(ha_rad)
        sin_elev = max(-1.0, min(1.0, sin_elev))
        elev_deg = round(math.degrees(math.asin(sin_elev)), 2)

        # Min and max elevation over 24h cycle
        noon_elev = math.degrees(math.asin(max(-1.0, min(1.0, math.sin(lat_rad) * math.sin(delta_rad) + math.cos(lat_rad) * math.cos(delta_rad)))))
        midnight_elev = math.degrees(math.asin(max(-1.0, min(1.0, math.sin(lat_rad) * math.sin(delta_rad) - math.cos(lat_rad) * math.cos(delta_rad)))))

        is_polar_day = midnight_elev > 0.0
        is_polar_night = noon_elev < 0.0

        # Turbine icing index: high humidity + temperature between -10°C and 0°C + wind
        icing_risk = "NONE"
        if -12.0 <= target.temperature_c <= 1.0 and target.relative_humidity_pct > 80.0:
            if target.wind_speed_ms > 10.0 or target.precipitation_rate_mmh > 0:
                icing_risk = "SEVERE"
            else:
                icing_risk = "MODERATE"
        elif target.temperature_c < -12.0 and target.relative_humidity_pct > 90.0:
            icing_risk = "LOW"

        # Storm warning: wind speed > 20 m/s or wind gust > 25 m/s
        storm_warning = target.wind_speed_ms >= 20.0 or target.wind_gust_ms >= 25.0

        # Blizzard: wind > 15 m/s, temp < -5°C, visibility < 1 km
        blizzard_prob = 0.0
        if target.wind_speed_ms >= 15.0 and target.temperature_c <= -5.0:
            blizzard_prob = 0.85 if target.visibility_km <= 1.0 else 0.45

        return PolarWeatherConditions(
            station_id=self.station_id,
            timestamp=dt,
            solar_elevation_deg=elev_deg,
            is_polar_day=is_polar_day,
            is_polar_night=is_polar_night,
            effective_air_density_kgm3=target.air_density_kgm3,
            icing_risk_level=icing_risk,
            storm_warning=storm_warning,
            blizzard_probability=blizzard_prob,
        )
