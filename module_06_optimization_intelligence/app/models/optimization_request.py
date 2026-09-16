"""
Optimization Request Models.

Data structures representing inputs from Module 02 (Mission), Module 03 (Energy),
Module 04 (Forecast), Module 05 (Diagnostics), and Module 07 (Safety/Reserve).
"""

from __future__ import annotations

from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, ConfigDict, Field


class MissionPriority(str, Enum):
    """Mission Priority Levels (P0 highest, P4 lowest)."""
    P0 = "P0"  # Critical Life-Support / Survival
    P1 = "P1"  # Essential Research / Station Infrastructure
    P2 = "P2"  # Primary Scientific Activities
    P3 = "P3"  # Secondary Operations / Flexible Workloads
    P4 = "P4"  # Optional / Deferrable Maintenance


class MissionProfile(BaseModel):
    """Mission specification ingested from Module 02."""
    mission_id: str
    name: str
    priority: MissionPriority = MissionPriority.P2
    type: str = "SCIENTIFIC"  # LIFE_SUPPORT, RESEARCH, COMPUTING, MAINTENANCE
    required_power_kw: float
    min_power_kw: float
    max_power_kw: float
    energy_required_kwh: float
    duration_minutes: int
    deadline_minutes: int
    earliest_start_minutes: int = 0
    flexibility: bool = True
    interruptibility: bool = False
    shiftability: bool = True
    dependencies: List[str] = Field(default_factory=list)
    buffer_kwh: float = 0.0
    has_reduced_power_mode: bool = False
    reduced_power_min_kw: Optional[float] = None


class EnergyStateInput(BaseModel):
    """Current system energy state ingested from Module 03."""
    timestamp: str = ""
    current_solar_kw: float = 0.0
    current_wind_kw: float = 0.0
    current_load_kw: float = 0.0
    battery_soc: float = 0.8  # 0.0 to 1.0
    battery_capacity_kwh: float = 1000.0
    usable_battery_kwh: float = 800.0
    max_battery_charge_kw: float = 250.0
    max_battery_discharge_kw: float = 250.0
    battery_charge_efficiency: float = 0.95
    battery_discharge_efficiency: float = 0.95
    battery_soh: float = 0.95  # State of Health (0.0 to 1.0)
    battery_cycle_count: float = 150.0
    hydrogen_energy_kwh: float = 2000.0
    hydrogen_tank_capacity_kwh: float = 5000.0
    max_hydrogen_charge_kw: float = 150.0
    max_hydrogen_discharge_kw: float = 150.0
    fuel_cell_efficiency: float = 0.60
    electrolyzer_efficiency: float = 0.70
    min_protected_hydrogen_kwh: float = 500.0
    thermal_storage_kwh: float = 0.0


class ForecastDataInput(BaseModel):
    """Forecast trajectories ingested from Module 04."""
    model_config = ConfigDict(protected_namespaces=())

    forecast_id: str = "FC-DEFAULT"
    model_version: str = "v1.0"
    created_at: str = ""
    time_step_minutes: int = 60
    solar_forecast_kw: List[float] = Field(default_factory=list)
    wind_forecast_kw: List[float] = Field(default_factory=list)
    load_forecast_kw: List[float] = Field(default_factory=list)
    uncertainty_pct: float = 0.10
    scenarios: Dict[str, Dict[str, List[float]]] = Field(default_factory=dict)


class EquipmentConstraintInput(BaseModel):
    """Equipment availability & derating ingested from Module 05."""
    equipment_id: str
    name: str
    available: bool = True
    derated_capacity_kw: float
    health_score: float = 1.0
    failure_risk: float = 0.01
    operating_limits: Dict[str, Any] = Field(default_factory=dict)


class ReserveConstraintInput(BaseModel):
    """Safety and reserve bounds ingested from Module 07."""
    station_id: str = "POLAR-STATION-ALPHA"
    required_reserve_kwh: float = 200.0
    protected_energy_kwh: float = 300.0
    safety_margin_pct: float = 0.15
    approved_operating_boundary_kw: float = 1000.0


class OptimizationMode(str, Enum):
    """Optimization Execution Mode."""
    DETERMINISTIC = "DETERMINISTIC"
    CONSERVATIVE = "CONSERVATIVE"
    SCENARIO = "SCENARIO"
    ROBUST = "ROBUST"


class ScenarioType(str, Enum):
    """Multi-Scenario Optimization Types."""
    BASELINE = "BASELINE"
    LOW_RENEWABLE = "LOW_RENEWABLE"
    HIGH_LOAD = "HIGH_LOAD"
    WIND_COLLAPSE = "WIND_COLLAPSE"
    SOLAR_DROP = "SOLAR_DROP"
    STORM = "STORM"
    EQUIPMENT_DEGRADATION = "EQUIPMENT_DEGRADATION"
    BATTERY_DEGRADATION = "BATTERY_DEGRADATION"
    HYDROGEN_SHORTAGE = "HYDROGEN_SHORTAGE"


class OptimizationRequest(BaseModel):
    """Complete Input Request Payload for Module 06 Optimization."""
    request_id: str
    station_id: str = "POLAR-STATION-ALPHA"
    created_at: str = ""
    horizon_minutes: int = 1440  # 24 hours by default
    time_step_minutes: int = 60   # 1 hour by default
    mode: OptimizationMode = OptimizationMode.DETERMINISTIC
    scenario: ScenarioType = ScenarioType.BASELINE
    solver_name: Optional[str] = None  # "ortools" or "pyomo"
    max_solve_time_seconds: Optional[float] = None
    lexicographic_mode: bool = False

    # Ingested Subsystem Inputs
    missions: List[MissionProfile] = Field(default_factory=list)
    energy_state: EnergyStateInput = Field(default_factory=EnergyStateInput)
    forecast: ForecastDataInput = Field(default_factory=ForecastDataInput)
    equipment: List[EquipmentConstraintInput] = Field(default_factory=list)
    reserve: ReserveConstraintInput = Field(default_factory=ReserveConstraintInput)

    # Custom Objective Weights Overrides
    weight_overrides: Dict[str, float] = Field(default_factory=dict)

