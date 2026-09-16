"""
Module 07 Settings and Configuration.

Pydantic Settings v2 configuration for Safety + Reserve Intelligence.
Allows setting reserve multipliers, thresholds, sensor tolerances, and endpoints.
"""

from __future__ import annotations

from typing import Dict
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for Module 07 Safety + Reserve Intelligence."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Station Identity & Network
    station_id: str = "POLAR-STATION-ALPHA"
    host: str = "0.0.0.0"
    port: int = 8007
    environment: str = "development"
    debug: bool = True
    mock_mode: bool = True

    # Databases & Caching
    database_url: str = "sqlite+aiosqlite:///./module_07.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_name: str = "frost:events:safety"

    # Inter-Module Service Endpoints
    m01_orchestrator_url: str = "http://localhost:8001"
    m02_mission_intelligence_url: str = "http://localhost:8002"
    m03_energy_intelligence_url: str = "http://localhost:8003"
    m04_forecast_intelligence_url: str = "http://localhost:8004"
    m05_diagnostic_intelligence_url: str = "http://localhost:8005"
    m06_optimization_intelligence_url: str = "http://localhost:8006"
    m08_execution_url: str = "http://localhost:8008"

    # Core Safety & Reserve Thresholds (Configurable & Versioned)
    minimum_battery_soc_pct: float = 20.0
    maximum_battery_soc_pct: float = 95.0
    critical_battery_soc_pct: float = 15.0
    critical_battery_temp_c: float = 45.0  # Thermal emergency threshold

    minimum_hydrogen_level_pct: float = 15.0
    maximum_hydrogen_pressure_bar: float = 350.0  # Pressure emergency threshold

    critical_load_kw: float = 40.0
    emergency_reserve_kwh: float = 200.0
    reserve_horizon_hours: int = 24

    # Multipliers & Margins
    uncertainty_margin_factor: float = 1.25
    equipment_risk_margin_factor: float = 1.15
    storm_reserve_multiplier: float = 1.50
    low_wind_reserve_multiplier: float = 1.30
    sensor_stale_tolerance_seconds: int = 300  # 5 minutes

    # Fail-safe Policies
    sensor_failure_policy: str = "REQUIRES_REPLAN"  # "REQUIRES_REPLAN", "UNSAFE", "EMERGENCY"
    policy_version: str = "7.1.0"


def get_settings() -> Settings:
    """Dependency injector for settings."""
    return Settings()
