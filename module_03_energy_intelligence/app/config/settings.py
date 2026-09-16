"""
Frost OS Module 03 — Application Settings.

Pydantic Settings for Energy Intelligence, containing physical thresholds,
tolerances, broker URLs, and storage model parameters.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for Energy Intelligence."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service identification
    app_name: str = "frost-energy-intelligence"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", description="Runtime environment")
    debug: bool = Field(default=False, description="Enable debug logging")
    station_id: str = Field(default="FROST-STATION-ALPHA", description="Station identifier")
    service_port: int = Field(default=8003, description="HTTP server port")

    # Database & TimescaleDB
    database_url: str = Field(
        default="postgresql+asyncpg://frost:frost_polar_2026@localhost:5432/frost_energy",
        description="Async database connection string",
    )

    # Redis Streams
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    stream_energy: str = Field(
        default="frost:events:energy",
        description="Redis stream key for energy state events",
    )
    redis_stream_energy: str = Field(
        default="frost:events:energy",
        description="Redis stream key for energy state events",
    )

    # MQTT Ingestion
    mqtt_broker_host: str = Field(default="localhost", description="MQTT broker hostname")
    mqtt_broker_port: int = Field(default=1883, description="MQTT broker port")
    mqtt_client_id: str = Field(default="frost-m03-telemetry", description="MQTT client ID")
    mqtt_topic_prefix: str = Field(default="frost", description="Root MQTT topic prefix")
    mqtt_enabled: bool = Field(default=False, description="Enable active MQTT background listener")

    # Physical Thresholds & Anomaly Tolerances
    power_balance_tolerance_kw: float = Field(
        default=5.0,
        ge=0.0,
        description="Allowable residual discrepancy in energy balance before alert (kW)",
    )
    power_balance_tolerance_pct: float = Field(
        default=5.0,
        ge=0.0,
        le=100.0,
        description="Allowable residual percentage in energy balance",
    )
    stale_sensor_threshold_seconds: float = Field(
        default=30.0,
        ge=1.0,
        description="Duration before inactive telemetry is marked STALE",
    )
    max_rate_of_change_kw_per_sec: float = Field(
        default=100.0,
        ge=1.0,
        description="Maximum plausible rate of change for generation/load before suspect flag",
    )

    # Storage Reserve Thresholds
    battery_low_soc_threshold_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    battery_critical_soc_threshold_pct: float = Field(default=10.0, ge=0.0, le=100.0)
    hydrogen_low_level_pct: float = Field(default=20.0, ge=0.0, le=100.0)
    hydrogen_critical_level_pct: float = Field(default=10.0, ge=0.0, le=100.0)

    # Event Alert Triggers
    generation_drop_alert_pct: float = Field(default=30.0, ge=5.0, le=100.0)
    load_spike_alert_pct: float = Field(default=25.0, ge=5.0, le=100.0)

    # Polar Station Default Asset Ratings
    battery_capacity_kwh: float = Field(default=6000.0, gt=0.0)
    battery_min_soc_pct: float = Field(default=15.0, ge=0.0, le=100.0)
    battery_max_soc_pct: float = Field(default=95.0, ge=0.0, le=100.0)
    battery_max_discharge_kw: float = Field(default=350.0, gt=0.0)
    battery_max_charge_kw: float = Field(default=300.0, gt=0.0)
    battery_discharge_efficiency: float = Field(default=0.95, gt=0.0, le=1.0)
    battery_charge_efficiency: float = Field(default=0.95, gt=0.0, le=1.0)

    hydrogen_capacity_kwh: float = Field(default=10000.0, gt=0.0)
    hydrogen_min_reserve_pct: float = Field(default=15.0, ge=0.0, le=100.0)
    hydrogen_fuel_cell_efficiency: float = Field(default=0.60, gt=0.0, le=1.0)
    hydrogen_max_fuel_cell_kw: float = Field(default=200.0, gt=0.0)

    # Operating Mode
    mock_mode: bool = Field(default=False, description="Run in mock/test mode without external brokers")
    log_level: str = Field(default="INFO", description="Logging level")
