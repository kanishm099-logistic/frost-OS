"""
Frost OS Module 04 — Weather & NWP Data Models.

Represents local meteorological telemetry, external NWP (Numerical Weather Prediction)
forecast grids, and polar atmospheric conditions.
"""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class WeatherCondition(str, enum.Enum):
    """Polar meteorological condition classification."""
    CLEAR = "CLEAR"
    PARTLY_CLOUDY = "PARTLY_CLOUDY"
    OVERCAST = "OVERCAST"
    LIGHT_SNOW = "LIGHT_SNOW"
    BLIZZARD = "BLIZZARD"
    FOG = "FOG"
    ICE_FOG = "ICE_FOG"
    STORM = "STORM"


class WeatherObservation(BaseModel):
    """
    Physical surface weather observation at a polar station.
    """
    station_id: str = Field(..., description="Station identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Observation timestamp (UTC)",
    )
    temperature_c: float = Field(..., description="Ambient air temperature in Celsius")
    pressure_hpa: float = Field(default=985.0, description="Surface barometric pressure in hPa")
    wind_speed_ms: float = Field(..., ge=0.0, description="Wind speed at 10m/hub height in m/s")
    wind_direction_deg: float = Field(default=0.0, ge=0.0, le=360.0, description="Wind azimuth degrees")
    wind_gust_ms: float = Field(default=0.0, ge=0.0, description="Peak gust speed in m/s")
    cloud_cover_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Cloud cover percentage")
    global_horizontal_irradiance_wm2: float = Field(
        default=0.0, ge=0.0, description="GHI solar irradiance (W/m²)"
    )
    direct_normal_irradiance_wm2: float = Field(
        default=0.0, ge=0.0, description="DNI solar irradiance (W/m²)"
    )
    diffuse_horizontal_irradiance_wm2: float = Field(
        default=0.0, ge=0.0, description="DHI solar irradiance (W/m²)"
    )
    relative_humidity_pct: float = Field(default=75.0, ge=0.0, le=100.0, description="Relative humidity %")
    precipitation_rate_mmh: float = Field(default=0.0, ge=0.0, description="Snowfall/precipitation rate mm/h")
    visibility_km: float = Field(default=10.0, ge=0.0, description="Atmospheric visibility in km")
    icing_index: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Turbine/sensor ice accumulation risk index (0-1)"
    )
    condition: WeatherCondition = Field(default=WeatherCondition.CLEAR)
    source: str = Field(default="station_sensor", description="Source: station_sensor, nwp, downscaled")

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @property
    def air_density_kgm3(self) -> float:
        """
        Calculate moist air density using ideal gas law adjusted for polar cold:
        rho = P / (R_specific * T_kelvin)
        R_specific for dry air = 287.058 J/(kg*K)
        """
        temp_k = self.temperature_c + 273.15
        if temp_k <= 0:
            temp_k = 243.15  # Fallback to -30°C if corrupt
        p_pa = self.pressure_hpa * 100.0
        return round(p_pa / (287.058 * temp_k), 4)


class NWPForecastRecord(BaseModel):
    """
    Raw Numerical Weather Prediction grid forecast from ECMWF/NOAA/GFS.
    """
    model_config = {"protected_namespaces": ()}

    model_name: str = Field(default="ECMWF-HRES", description="NWP source model")
    station_id: str = Field(..., description="Target station identifier")
    issue_time: datetime = Field(..., description="NWP model cycle issue time (UTC)")
    valid_time: datetime = Field(..., description="Target forecast valid time (UTC)")
    lead_time_hours: float = Field(..., ge=0.0, description="Forecast horizon in hours")

    temperature_c: float = Field(..., description="Predicted 2m temperature (°C)")
    pressure_hpa: float = Field(default=985.0, description="Predicted surface pressure (hPa)")
    wind_speed_ms: float = Field(..., ge=0.0, description="Predicted 10m/100m wind speed (m/s)")
    wind_direction_deg: float = Field(default=0.0, ge=0.0, le=360.0, description="Predicted wind direction")
    cloud_cover_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Predicted cloud cover (%)")
    solar_radiation_wm2: float = Field(default=0.0, ge=0.0, description="Predicted surface solar downward flux")
    precipitation_mm: float = Field(default=0.0, ge=0.0, description="Predicted accumulated precipitation")
    snowfall_risk: bool = Field(default=False, description="Flag indicating expected snowfall")

    @field_validator("issue_time", "valid_time", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class PolarWeatherConditions(BaseModel):
    """Derived polar meteorological diagnostics."""
    station_id: str
    timestamp: datetime
    solar_elevation_deg: float
    is_polar_day: bool
    is_polar_night: bool
    effective_air_density_kgm3: float
    icing_risk_level: str  # NONE, LOW, MODERATE, SEVERE
    storm_warning: bool
    blizzard_probability: float = Field(default=0.0, ge=0.0, le=1.0)
