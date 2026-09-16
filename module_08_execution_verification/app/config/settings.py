"""
Module 08 Settings and Configuration.

Pydantic Settings v2 configuration for Execution + Verification Intelligence.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for Module 08 Execution + Verification Intelligence."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Station Identity & Network
    station_id: str = "POLAR-STATION-ALPHA"
    host: str = "0.0.0.0"
    port: int = 8008
    environment: str = "development"
    debug: bool = True
    mock_mode: bool = True

    # Databases & Caching
    database_url: str = "sqlite+aiosqlite:///./module_08.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_stream_name: str = "frost:events:execution"

    # Inter-Module Service Endpoints
    m01_orchestrator_url: str = "http://localhost:8001"
    m02_mission_intelligence_url: str = "http://localhost:8002"
    m03_energy_intelligence_url: str = "http://localhost:8003"
    m04_forecast_intelligence_url: str = "http://localhost:8004"
    m05_diagnostic_intelligence_url: str = "http://localhost:8005"
    m06_optimization_intelligence_url: str = "http://localhost:8006"
    m07_safety_reserve_url: str = "http://localhost:8007"

    # Hardware & Command Limits
    default_command_timeout_seconds: float = 15.0
    telemetry_observation_window_seconds: float = 5.0
    verification_power_tolerance_kw: float = 5.0
    verification_soc_tolerance_pct: float = 2.0
    resource_lock_timeout_seconds: int = 60

    # Protocol Endpoints
    modbus_host: str = "localhost"
    modbus_port: int = 502
    opcua_endpoint: str = "opc.tcp://localhost:4840"
    can_channel: str = "vcan0"
    mqtt_broker: str = "localhost"
    mqtt_port: int = 1883


def get_settings() -> Settings:
    """Dependency injector for settings."""
    return Settings()
