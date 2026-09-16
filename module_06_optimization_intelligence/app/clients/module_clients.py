"""
Inter-Module Subsystem Clients & Mocks.

Provides HTTP & Mock clients for communicating with Module 02 (Mission), Module 03 (Energy),
Module 04 (Forecast), Module 05 (Diagnostic), Module 07 (Reserve/Safety), and Module 08 (Execution).
"""

from __future__ import annotations

from typing import List, Dict, Any
from app.models.optimization_request import (
    MissionProfile,
    MissionPriority,
    EnergyStateInput,
    ForecastDataInput,
    EquipmentConstraintInput,
    ReserveConstraintInput,
)


class MockSubsystemClients:
    """Mock Provider supplying realistic polar station operational inputs for testing and demo."""

    @staticmethod
    def get_mock_missions() -> List[MissionProfile]:
        """Return sample set of polar research station missions."""
        return [
            MissionProfile(
                mission_id="MIS-LIFE-01",
                name="Life Support & Thermal Maintenance",
                priority=MissionPriority.P0,
                type="LIFE_SUPPORT",
                required_power_kw=100.0,
                min_power_kw=100.0,
                max_power_kw=120.0,
                energy_required_kwh=2400.0,
                duration_minutes=1440,
                deadline_minutes=1440,
                flexibility=False,
                interruptibility=False,
                shiftability=False,
            ),
            MissionProfile(
                mission_id="MIS-RES-01",
                name="Atmospheric Lidar Radar Sampling",
                priority=MissionPriority.P1,
                type="RESEARCH",
                required_power_kw=150.0,
                min_power_kw=150.0,
                max_power_kw=180.0,
                energy_required_kwh=1800.0,
                duration_minutes=720,
                deadline_minutes=1440,
                flexibility=True,
                interruptibility=True,
                shiftability=True,
            ),
            MissionProfile(
                mission_id="MIS-LAB-01",
                name="Deep Ice Core Cryo-Laboratory",
                priority=MissionPriority.P2,
                type="RESEARCH",
                required_power_kw=120.0,
                min_power_kw=90.0,
                max_power_kw=140.0,
                energy_required_kwh=720.0,
                duration_minutes=360,
                deadline_minutes=1440,
                flexibility=True,
                interruptibility=True,
                shiftability=True,
                has_reduced_power_mode=True,
                reduced_power_min_kw=90.0,
            ),
            MissionProfile(
                mission_id="MIS-COMP-01",
                name="Climate Simulation Compute Workload",
                priority=MissionPriority.P3,
                type="COMPUTING",
                required_power_kw=120.0,
                min_power_kw=60.0,
                max_power_kw=150.0,
                energy_required_kwh=360.0,
                duration_minutes=180,
                deadline_minutes=1440,
                flexibility=True,
                interruptibility=True,
                shiftability=True,
            ),
        ]

    @staticmethod
    def get_mock_energy_state() -> EnergyStateInput:
        """Return sample EnergyStateInput."""
        return EnergyStateInput(
            current_solar_kw=250.0,
            current_wind_kw=200.0,
            current_load_kw=120.0,
            battery_soc=0.80,
            battery_capacity_kwh=1000.0,
            usable_battery_kwh=800.0,
            max_battery_charge_kw=300.0,
            max_battery_discharge_kw=300.0,
            battery_charge_efficiency=0.95,
            battery_discharge_efficiency=0.95,
            battery_soh=0.95,
            hydrogen_energy_kwh=2500.0,
            max_hydrogen_charge_kw=150.0,
            max_hydrogen_discharge_kw=150.0,
            hydrogen_tank_capacity_kwh=5000.0,
            fuel_cell_efficiency=0.60,
            electrolyzer_efficiency=0.70,
            min_protected_hydrogen_kwh=500.0,
        )

    @staticmethod
    def get_mock_forecast(n_steps: int = 24, scenario: str = "BASELINE") -> ForecastDataInput:
        """Return sample forecast trajectory across time steps."""
        if scenario == "SUMMER":
            solar = [300.0 if 6 <= (t % 24) <= 18 else 0.0 for t in range(n_steps)]
            wind = [150.0 + (t % 5) * 10 for t in range(n_steps)]
            load = [120.0 for _ in range(n_steps)]
        elif scenario == "POLAR_NIGHT":
            solar = [0.0 for _ in range(n_steps)]
            wind = [80.0 for _ in range(n_steps)]
            load = [150.0 for _ in range(n_steps)]
        else:  # BASELINE
            solar = [200.0 if 8 <= (t % 24) <= 16 else 0.0 for t in range(n_steps)]
            wind = [180.0 for _ in range(n_steps)]
            load = [100.0 for _ in range(n_steps)]

        return ForecastDataInput(
            forecast_id="FC-MOCK-01",
            model_version="v1.0",
            time_step_minutes=60,
            solar_forecast_kw=solar,
            wind_forecast_kw=wind,
            load_forecast_kw=load,
        )

    @staticmethod
    def get_mock_equipment() -> List[EquipmentConstraintInput]:
        """Return sample equipment derating & health constraints."""
        return [
            EquipmentConstraintInput(
                equipment_id="TURBINE-WIND-01",
                name="Nordic Wind Turbine 1",
                available=True,
                derated_capacity_kw=250.0,
                health_score=0.95,
            ),
            EquipmentConstraintInput(
                equipment_id="SOLAR-ARRAY-01",
                name="Bifacial Solar Array",
                available=True,
                derated_capacity_kw=350.0,
                health_score=0.98,
            ),
        ]

    @staticmethod
    def get_mock_reserve() -> ReserveConstraintInput:
        """Return sample Module 07 station reserve limits."""
        return ReserveConstraintInput(
            station_id="POLAR-STATION-ALPHA",
            required_reserve_kwh=300.0,
            protected_energy_kwh=400.0,
            safety_margin_pct=0.15,
        )
