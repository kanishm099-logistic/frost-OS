"""
Versioned Reserve Policy Parameters.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReservePolicy(BaseModel):
    """Configurable reserve calculation policy."""
    policy_version: str = "7.1.0"
    description: str = "Polar Research Station Standard Reserve Policy"
    
    # Storage Safety Limits
    minimum_battery_soc_pct: float = 20.0
    critical_battery_soc_pct: float = 15.0
    maximum_battery_soc_pct: float = 95.0
    
    minimum_hydrogen_level_pct: float = 15.0
    critical_hydrogen_level_pct: float = 10.0
    
    # Emergency & Base Station Requirements
    emergency_reserve_kwh: float = 200.0
    critical_load_kw: float = 40.0
    reserve_horizon_hours: int = 24
    
    # Dynamic Multipliers & Margins
    uncertainty_margin_factor: float = 1.25
    equipment_risk_margin_factor: float = 1.15
    storm_reserve_multiplier: float = 1.50
    low_wind_reserve_multiplier: float = 1.30
    
    # Non-double counting flag
    deduct_mission_buffers_from_station_reserve: bool = True
