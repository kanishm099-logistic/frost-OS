"""
Frost OS Module 04 — System Configuration & Settings.

Central configuration using Pydantic Settings. Covers polar station parameters,
turbine specifications, solar arrays, storage parameters, forecast horizons,
and database / broker connections.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Module 04 runtime and physical parameters."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service metadata
    app_name: str = "Frost OS Module 04: Forecast Intelligence"
    app_version: str = "0.1.0"
    app_env: Literal["development", "testing", "production"] = "development"
    debug: bool = False
    api_prefix: str = ""
    port: int = 8004

    # Station coordinates & identification (Defaults to Halley VI Antarctic Station)
    station_id: str = "polar-station-alpha"
    station_name: str = "Halley VI Research Station"
    latitude: float = Field(default=-75.58, ge=-90.0, le=90.0, description="Latitude in decimal degrees")
    longitude: float = Field(default=-26.66, ge=-180.0, le=180.0, description="Longitude in decimal degrees")
    altitude_m: float = Field(default=30.0, ge=0.0, description="Elevation above sea level in meters")

    # Solar PV parameters
    solar_installed_capacity_kw: float = Field(default=80.0, gt=0.0, description="Nameplate solar capacity (kW)")
    solar_efficiency: float = Field(default=0.19, gt=0.0, le=1.0, description="Module efficiency")
    solar_temperature_coeff: float = Field(default=-0.004, description="Power temp coefficient (%/°C from 25°C)")
    solar_panel_area_m2: float = Field(default=420.0, gt=0.0, description="Total PV array area in m²")
    solar_tilt_deg: float = Field(default=65.0, ge=0.0, le=90.0, description="Panel tilt from horizontal")
    solar_azimuth_deg: float = Field(default=0.0, description="Panel azimuth (0° North for southern hemisphere)")

    # Wind turbine parameters
    wind_installed_capacity_kw: float = Field(default=120.0, gt=0.0, description="Total rated wind capacity (kW)")
    wind_cut_in_speed_ms: float = Field(default=3.0, ge=0.0, description="Turbine cut-in speed (m/s)")
    wind_rated_speed_ms: float = Field(default=12.0, gt=0.0, description="Turbine rated speed (m/s)")
    wind_cut_out_speed_ms: float = Field(default=25.0, gt=0.0, description="Turbine storm cut-out speed (m/s)")
    wind_rotor_diameter_m: float = Field(default=20.0, gt=0.0, description="Rotor diameter (m)")
    wind_hub_height_m: float = Field(default=25.0, gt=0.0, description="Tower hub height (m)")
    wind_power_coeff_cp: float = Field(default=0.42, gt=0.0, le=0.593, description="Betz aerodynamic coefficient")

    # Storage parameters
    battery_capacity_kwh: float = Field(default=500.0, gt=0.0, description="Nominal BESS capacity (kWh)")
    battery_min_soc_pct: float = Field(default=15.0, ge=0.0, le=100.0, description="Minimum allowable reserve SOC (%)")
    battery_max_soc_pct: float = Field(default=95.0, ge=0.0, le=100.0, description="Maximum allowable SOC (%)")
    battery_max_charge_kw: float = Field(default=150.0, gt=0.0, description="Max battery charge rate (kW)")
    battery_max_discharge_kw: float = Field(default=150.0, gt=0.0, description="Max battery discharge rate (kW)")
    battery_roundtrip_efficiency: float = Field(default=0.92, gt=0.0, le=1.0, description="BESS roundtrip efficiency")

    hydrogen_capacity_kwh: float = Field(default=2500.0, gt=0.0, description="Long-duration H2 buffer capacity (kWh)")
    hydrogen_min_level_pct: float = Field(default=10.0, ge=0.0, le=100.0, description="Minimum reserve H2 level (%)")
    hydrogen_fuel_cell_efficiency: float = Field(default=0.55, gt=0.0, le=1.0, description="Fuel cell efficiency")
    hydrogen_electrolyzer_efficiency: float = Field(default=0.65, gt=0.0, le=1.0, description="Electrolyzer efficiency")

    # Demand & thermal sensitivity
    base_station_load_kw: float = Field(default=35.0, gt=0.0, description="Baseline life support demand (kW)")
    heating_temp_coefficient: float = Field(
        default=0.85,
        description="Demand increase in kW per °C ambient temperature below indoor target",
    )
    indoor_target_temp_c: float = Field(default=18.0, description="Nominal station indoor target temperature (°C)")

    # Horizons & resolution
    horizons: list[str] = Field(
        default_factory=lambda: ["5m", "15m", "30m", "1h", "6h", "24h", "48h", "72h"],
        description="Supported forecast horizons",
    )
    horizon_minutes_map: dict[str, int] = Field(
        default_factory=lambda: {
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "6h": 360,
            "24h": 1440,
            "48h": 2880,
            "72h": 4320,
        }
    )

    # Uncertainty & quality thresholds
    confidence_decay_half_life_hours: float = Field(
        default=36.0,
        description="Lead-time half-life in hours where forecast confidence degrades by 50%",
    )
    stale_data_threshold_seconds: int = Field(
        default=300,
        description="Telemetry older than this triggers quality degradation",
    )

    # Persistence & Messaging URLs
    database_url: str = Field(
        default="sqlite+aiosqlite:///:memory:",
        description="Database connection URL (PostgreSQL/TimescaleDB or SQLite for test)",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for streams",
    )
    redis_stream_name: str = "frost:events:forecast"

    # Upstream integration URLs (for optional pull / notifications)
    orchestrator_service_url: str = "http://localhost:8001"
    mission_service_url: str = "http://localhost:8002"
    energy_service_url: str = "http://localhost:8003"
    diagnostic_service_url: str = "http://localhost:8005"
    optimization_service_url: str = "http://localhost:8006"
    safety_service_url: str = "http://localhost:8007"

    # NWP Provider
    nwp_provider_type: Literal["mock", "ecmwf", "noaa"] = "mock"
    nwp_api_key: str = "mock-key"
    nwp_cache_ttl_seconds: int = 1800


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
