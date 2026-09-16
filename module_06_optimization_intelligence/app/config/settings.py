"""
Module 06 Settings and Configuration.

Provides configurable settings using Pydantic Settings v2.
Allows explicit configuration of solver time limits, objective weights,
lexicographic modes, database URLs, and inter-module service URLs.
"""

from __future__ import annotations

from typing import Dict, List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for Module 06 Optimization Intelligence."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Station Identity & Network
    station_id: str = "POLAR-STATION-ALPHA"
    host: str = "0.0.0.0"
    port: int = 8006
    environment: str = "development"
    debug: bool = True
    mock_mode: bool = True

    # Solver Configuration
    default_solver: str = "ortools"  # "ortools" or "pyomo"
    max_solve_time_seconds: float = 10.0
    mip_gap: float = 0.01  # 1% relative optimality gap
    thread_count: int = 4

    # Default Optimization Parameters
    default_horizon_minutes: int = 1440  # 24h
    default_time_step_minutes: int = 60   # 1h

    # Databases & Caching
    database_url: str = "sqlite+aiosqlite:///./module_06.db"
    redis_url: str = "redis://localhost:6379/0"

    # Inter-Module Service Endpoints
    m01_orchestrator_url: str = "http://localhost:8001"
    m02_mission_intelligence_url: str = "http://localhost:8002"
    m03_energy_intelligence_url: str = "http://localhost:8003"
    m04_forecast_intelligence_url: str = "http://localhost:8004"
    m05_diagnostic_intelligence_url: str = "http://localhost:8005"
    m07_safety_reserve_url: str = "http://localhost:8007"
    m08_execution_url: str = "http://localhost:8008"

    # Priority Weights (P0, P1, P2, P3, P4)
    priority_weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "P0": 100000.0,
            "P1": 10000.0,
            "P2": 1000.0,
            "P3": 100.0,
            "P4": 10.0,
        }
    )

    # Configurable Objective Function Weights (Maximized / Minimized)
    # Never hide objective weights inside code!
    weight_mission_value: float = 100.0
    weight_priority_completion: float = 500.0
    weight_renewable_utilization: float = 50.0
    weight_energy_efficiency: float = 30.0
    weight_deadline_compliance: float = 200.0
    weight_storage_health: float = 40.0
    weight_flexible_load_alignment: float = 25.0

    # Penalties (Subtracted from Objective)
    penalty_energy_waste: float = 20.0
    penalty_renewable_curtailment: float = 15.0
    penalty_battery_cycling: float = 30.0
    penalty_hydrogen_consumption: float = 60.0  # Hydrogen is long-term reserve
    penalty_load_disruption: float = 150.0
    penalty_mission_delay: float = 80.0
    penalty_equipment_risk: float = 100.0
    penalty_reserve_violation: float = 100000.0

    # Lexicographic Priority Mode
    enable_lexicographic_mode: bool = False
    lexicographic_order: List[str] = Field(
        default_factory=lambda: [
            "P0_PROTECTION",
            "P1_COMPLETION",
            "RESERVE_PRESERVATION",
            "DEADLINE_COMPLIANCE",
            "P2_COMPLETION",
            "P3_P4_COMPLETION",
            "RENEWABLE_UTILIZATION",
            "STORAGE_HEALTH",
        ]
    )


def get_settings() -> Settings:
    """Dependency injector for settings."""
    return Settings()
