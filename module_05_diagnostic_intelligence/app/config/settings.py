"""
Frost OS Module 05 — Application Settings.

Pydantic Settings for Diagnostic Intelligence, containing anomaly thresholds,
health scoring weights, equipment limits, service URLs, and infrastructure config.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for Diagnostic Intelligence."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Service Identity ──────────────────────────────────────────────
    app_name: str = "frost-diagnostic-intelligence"
    app_version: str = "0.1.0"
    environment: Literal["development", "testing", "production"] = "development"
    debug: bool = Field(default=False, description="Enable debug logging")
    station_id: str = Field(default="FROST-STATION-ALPHA", description="Station identifier")
    service_host: str = Field(default="0.0.0.0", description="HTTP server bind host")
    service_port: int = Field(default=8005, description="HTTP server port")

    # ── Database & TimescaleDB ────────────────────────────────────────
    database_url: str = Field(
        default="sqlite+aiosqlite:///:memory:",
        description="Async database connection string",
    )

    # ── Redis Streams ─────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )
    redis_stream_diagnostic: str = Field(
        default="frost:events:diagnostic",
        description="Redis stream key for diagnostic events",
    )
    redis_stream_energy: str = Field(
        default="frost:events:energy",
        description="Redis stream key to consume energy events from M03",
    )

    # ── Upstream Module URLs ──────────────────────────────────────────
    orchestrator_service_url: str = Field(default="http://localhost:8001", description="M01 Orchestrator")
    energy_service_url: str = Field(default="http://localhost:8003", description="M03 Energy Intelligence")
    forecast_service_url: str = Field(default="http://localhost:8004", description="M04 Forecast Intelligence")
    optimization_service_url: str = Field(default="http://localhost:8006", description="M06 Optimization")
    safety_service_url: str = Field(default="http://localhost:8007", description="M07 Safety")
    execution_service_url: str = Field(default="http://localhost:8008", description="M08 Execution")

    # ── Telemetry Processing ──────────────────────────────────────────
    stale_sensor_threshold_seconds: float = Field(
        default=60.0, ge=1.0,
        description="Duration before inactive telemetry is marked STALE",
    )
    max_rate_of_change_per_second: float = Field(
        default=100.0, ge=0.1,
        description="Default max plausible rate of change for most metrics",
    )
    telemetry_window_seconds: int = Field(
        default=300, ge=10,
        description="Rolling window size for feature extraction",
    )
    signal_resample_interval_seconds: int = Field(
        default=5, ge=1,
        description="Resample interval for signal alignment",
    )

    # ── Anomaly Detection Thresholds ──────────────────────────────────
    anomaly_zscore_threshold: float = Field(
        default=3.0, ge=1.0,
        description="Z-score threshold for statistical anomaly detection",
    )
    anomaly_iqr_multiplier: float = Field(
        default=1.5, ge=1.0,
        description="IQR multiplier for outlier detection",
    )
    ewma_alpha: float = Field(
        default=0.3, gt=0.0, le=1.0,
        description="EWMA smoothing factor for residual tracking",
    )
    residual_deviation_threshold: float = Field(
        default=0.15, ge=0.01,
        description="Fractional residual deviation to trigger anomaly (15% default)",
    )
    isolation_forest_contamination: float = Field(
        default=0.05, gt=0.0, lt=0.5,
        description="Expected anomaly contamination for Isolation Forest",
    )
    min_samples_for_ml: int = Field(
        default=100, ge=10,
        description="Minimum samples before ML models are used",
    )

    # ── Health Scoring Weights ────────────────────────────────────────
    health_weight_anomaly: float = Field(default=0.35, ge=0.0, le=1.0)
    health_weight_residual: float = Field(default=0.25, ge=0.0, le=1.0)
    health_weight_degradation: float = Field(default=0.25, ge=0.0, le=1.0)
    health_weight_maintenance: float = Field(default=0.15, ge=0.0, le=1.0)
    health_anomaly_decay_hours: float = Field(
        default=24.0, gt=0.0,
        description="Half-life for anomaly penalty decay",
    )

    # ── Health State Thresholds ───────────────────────────────────────
    health_threshold_healthy: float = Field(default=85.0, ge=0.0, le=100.0)
    health_threshold_monitored: float = Field(default=70.0, ge=0.0, le=100.0)
    health_threshold_degraded: float = Field(default=50.0, ge=0.0, le=100.0)
    health_threshold_at_risk: float = Field(default=30.0, ge=0.0, le=100.0)

    # ── Failure Risk Horizons ─────────────────────────────────────────
    risk_horizons_hours: list[float] = Field(
        default_factory=lambda: [1.0, 6.0, 24.0, 72.0, 168.0],
        description="Failure risk estimation horizons in hours",
    )

    # ── Wind Turbine Specific ─────────────────────────────────────────
    wind_rated_power_kw: float = Field(default=120.0, gt=0.0)
    wind_cut_in_speed_ms: float = Field(default=3.0, ge=0.0)
    wind_rated_speed_ms: float = Field(default=12.0, gt=0.0)
    wind_cut_out_speed_ms: float = Field(default=25.0, gt=0.0)
    wind_icing_temp_threshold_c: float = Field(default=-5.0, description="Below this, icing is possible")
    wind_power_curve_deviation_pct: float = Field(default=20.0, ge=5.0, le=100.0)

    # ── Solar Specific ────────────────────────────────────────────────
    solar_installed_capacity_kw: float = Field(default=80.0, gt=0.0)
    solar_panel_efficiency: float = Field(default=0.19, gt=0.0, le=1.0)
    solar_panel_area_m2: float = Field(default=420.0, gt=0.0)
    solar_temp_coefficient: float = Field(default=-0.004, description="Power temp coeff per °C from 25°C")

    # ── Battery Specific ──────────────────────────────────────────────
    battery_capacity_kwh: float = Field(default=6000.0, gt=0.0)
    battery_temp_high_c: float = Field(default=45.0)
    battery_temp_critical_c: float = Field(default=55.0)
    battery_voltage_imbalance_threshold_pct: float = Field(default=5.0, ge=1.0)

    # ── Diagnostic Intervals ──────────────────────────────────────────
    realtime_check_interval_seconds: float = Field(
        default=5.0, ge=1.0,
        description="Interval for lightweight real-time anomaly checks",
    )
    full_diagnostic_interval_seconds: float = Field(
        default=60.0, ge=10.0,
        description="Interval for full diagnostic analysis",
    )

    # ── Model Registry ────────────────────────────────────────────────
    model_storage_path: str = Field(
        default="models/",
        description="Local path for trained model artifacts",
    )

    # ── Operating Mode ────────────────────────────────────────────────
    mock_mode: bool = Field(default=True, description="Run in mock/test mode")
    log_level: str = Field(default="INFO", description="Logging level")


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
