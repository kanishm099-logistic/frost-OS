"""
Frost OS Module 01 — Application Settings.

Loads all configuration from environment variables using pydantic-settings.
Never hardcode secrets — use FROST_* env vars.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for the Frost Orchestrator."""

    model_config = SettingsConfigDict(
        env_prefix="FROST_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Identity ──────────────────────────────────────────────────────
    station_id: str = Field(default="FROST-STATION-ALPHA", description="Station identifier")
    service_name: str = Field(default="frost-orchestrator", description="Service name for logging")

    # ── Infrastructure ────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://frost:frost_secret@localhost:5432/frost_orchestrator",
        description="Async PostgreSQL connection URL",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # ── Module Service URLs ───────────────────────────────────────────
    mission_service_url: str = Field(default="http://localhost:8002", description="M02 Mission Intelligence")
    energy_service_url: str = Field(default="http://localhost:8003", description="M03 Energy Intelligence")
    forecast_service_url: str = Field(default="http://localhost:8004", description="M04 Forecast Intelligence")
    diagnostic_service_url: str = Field(default="http://localhost:8005", description="M05 Diagnostic Intelligence")
    optimizer_service_url: str = Field(default="http://localhost:8006", description="M06 Optimization Intelligence")
    reserve_service_url: str = Field(default="http://localhost:8007", description="M07 Safety+Reserve Intelligence")
    execution_service_url: str = Field(default="http://localhost:8008", description="M08 Execution+Verification")

    # ── Resilience ────────────────────────────────────────────────────
    client_timeout_seconds: float = Field(default=30.0, description="HTTP client request timeout")
    client_max_retries: int = Field(default=3, description="Max retry attempts per request")
    client_retry_base_delay: float = Field(default=1.0, description="Base delay for exponential backoff (seconds)")
    client_retry_max_delay: float = Field(default=8.0, description="Max delay cap for backoff (seconds)")
    circuit_breaker_failure_threshold: int = Field(default=5, description="Failures before circuit opens")
    circuit_breaker_recovery_timeout: float = Field(default=30.0, description="Seconds before half-open probe")

    # ── Auth ──────────────────────────────────────────────────────────
    jwt_secret: str = Field(default="change-me-in-production", description="JWT signing secret")
    jwt_algorithm: str = Field(default="HS256", description="JWT algorithm")
    jwt_expire_minutes: int = Field(default=60, description="JWT token expiry in minutes")

    # ── Feature Flags ─────────────────────────────────────────────────
    mock_mode: bool = Field(default=True, description="Use mock module clients instead of real HTTP calls")
    log_level: str = Field(default="INFO", description="Logging level")
    debug: bool = Field(default=False, description="Enable debug mode")

    # ── Redis Streams ─────────────────────────────────────────────────
    redis_consumer_group: str = Field(default="frost-orchestrator-group", description="Redis consumer group name")
    redis_consumer_name: str = Field(default="orchestrator-1", description="Redis consumer instance name")
    event_idempotency_ttl_seconds: int = Field(default=3600, description="TTL for processed event ID deduplication")

    # ── Action Plans ──────────────────────────────────────────────────
    action_plan_expiry_minutes: int = Field(default=30, description="Minutes before an unauthorized plan expires")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
