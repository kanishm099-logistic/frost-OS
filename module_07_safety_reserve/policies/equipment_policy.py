"""
Versioned Equipment Safety & Telemetry Fail-Safe Policy.
"""

from __future__ import annotations

from pydantic import BaseModel


class EquipmentPolicy(BaseModel):
    """Configurable equipment derating & data quality policy."""
    policy_version: str = "7.1.0"
    
    # Thermal & Hardware Thresholds
    max_battery_temp_c: float = 45.0  # Overtemperature threshold
    max_hydrogen_pressure_bar: float = 350.0  # Overpressure threshold
    max_inverter_ramp_kw_per_min: float = 50.0  # Inverter ramp rate limit
    
    # Telemetry Quality & Stale Thresholds
    sensor_stale_tolerance_seconds: int = 300  # 5 minutes
    
    # Fail-safe Behavior on Bad / Stale Data
    # "SAFE_WITH_REDUCED_CAPABILITY", "REQUIRES_REPLAN", "UNSAFE", "EMERGENCY"
    bad_telemetry_action: str = "REQUIRES_REPLAN"
    stale_telemetry_action: str = "REQUIRES_REPLAN"
