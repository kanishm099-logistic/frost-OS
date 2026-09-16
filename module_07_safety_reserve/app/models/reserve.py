"""
Station Energy Reserve Models.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Dict, Any
from pydantic import BaseModel, Field


class ReserveType(str, Enum):
    """Categorized reserve requirements."""
    STATION_RESERVE_KWH = "STATION_RESERVE_KWH"
    MISSION_RESERVE_KWH = "MISSION_RESERVE_KWH"
    EMERGENCY_RESERVE_KWH = "EMERGENCY_RESERVE_KWH"
    OPERATIONAL_RESERVE_KWH = "OPERATIONAL_RESERVE_KWH"
    TOTAL_PROTECTED_RESERVE_KWH = "TOTAL_PROTECTED_RESERVE_KWH"


class ReserveComponent(BaseModel):
    """Breakdown item of reserve formula component."""
    name: str
    reserve_type: ReserveType
    amount_kwh: float
    description: str
    is_protected: bool = True


class ReserveCalculation(BaseModel):
    """Dynamic station reserve calculation result."""
    station_id: str
    horizon_hours: int = 24
    
    # 5 Reserve Category Totals
    station_reserve_kwh: float
    mission_reserve_kwh: float
    emergency_reserve_kwh: float
    operational_reserve_kwh: float
    total_protected_reserve_kwh: float
    
    # Current Storage Availability
    current_battery_energy_kwh: float
    current_hydrogen_energy_kwh: float
    total_available_storage_kwh: float
    
    # Balance & Margin
    reserve_margin_kwh: float  # total_available - total_protected
    reserve_satisfied: bool
    
    # Time-to-Reserve Metrics
    time_to_reserve_expected_hours: float
    time_to_reserve_conservative_hours: float
    
    # Itemized Breakdown
    components: List[ReserveComponent] = Field(default_factory=list)
