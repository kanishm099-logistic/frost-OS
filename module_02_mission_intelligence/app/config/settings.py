"""
Frost OS Module 02 — Application Settings.

Pydantic Settings for Mission Intelligence service, with environment
variable overrides and configurable engine parameters.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Mission Intelligence configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Service identification
    app_name: str = "frost-mission-intelligence"
    app_version: str = "0.1.0"
    environment: str = Field(default="development", description="Runtime environment")
    debug: bool = Field(default=False, description="Enable debug mode")
    station_id: str = Field(default="FROST-STATION-ALPHA", description="Station identifier")
    service_port: int = Field(default=8002, description="HTTP server port")

    # Persistence
    database_url: str = Field(
        default="postgresql+asyncpg://frost:frost_polar_2026@localhost:5432/frost_missions",
        description="Async database connection string",
    )

    # Redis Streams
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for event streaming",
    )
    stream_missions: str = Field(
        default="frost:events:mission",
        description="Redis stream key for mission events",
    )
    redis_consumer_group: str = Field(
        default="mission-intelligence-group",
        description="Redis consumer group name",
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")

    # Priority Engine Scoring Weights (sum = 1.0)
    weight_priority: float = Field(default=0.35, ge=0.0, le=1.0)
    weight_urgency: float = Field(default=0.20, ge=0.0, le=1.0)
    weight_deadline: float = Field(default=0.15, ge=0.0, le=1.0)
    weight_mission_value: float = Field(default=0.15, ge=0.0, le=1.0)
    weight_flexibility: float = Field(default=0.10, ge=0.0, le=1.0)
    weight_energy_efficiency: float = Field(default=0.05, ge=0.0, le=1.0)

    # Buffer Engine Factors (kWh buffer multiplier by priority)
    buffer_factor_p0: float = Field(default=0.50, ge=0.0, description="Buffer for P0 life-critical (+50%)")
    buffer_factor_p1: float = Field(default=0.30, ge=0.0, description="Buffer for P1 mission-critical (+30%)")
    buffer_factor_p2: float = Field(default=0.15, ge=0.0, description="Buffer for P2 operational (+15%)")
    buffer_factor_p3: float = Field(default=0.05, ge=0.0, description="Buffer for P3 flexible (+5%)")
    buffer_factor_p4: float = Field(default=0.00, ge=0.0, description="Buffer for P4 deferrable (0%)")

    # Operational thresholds
    near_deadline_hours: float = Field(default=2.0, description="Threshold for near-deadline urgency alert")
    mock_mode: bool = Field(default=False, description="Run in mock/standalone mode")
