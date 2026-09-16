"""
Model Builder.

Assembles time grid, decision variable specifications, equipment bounds,
and initial condition summaries for documentation and audit logging.
The actual variable/constraint construction is done by the solver implementations.
"""

from __future__ import annotations

from typing import Dict, List, Any
from app.core.scheduler import SchedulerEngine, TimeGrid
from app.models.optimization_request import OptimizationRequest
from app.models.decision_variable import DecisionVariableSpec, VariableType


class ModelBuilder:
    """Pre-solver model specification builder for documentation and audit."""

    @staticmethod
    def build_variable_specs(request: OptimizationRequest) -> List[DecisionVariableSpec]:
        """Generate structured list of decision variable specifications."""
        grid = SchedulerEngine.create_time_grid(request.horizon_minutes, request.time_step_minutes)
        n_steps = grid.num_steps
        specs: List[DecisionVariableSpec] = []

        energy = request.energy_state
        batt_cap = energy.battery_capacity_kwh * energy.battery_soh

        for t in range(n_steps):
            # Battery variables
            specs.append(DecisionVariableSpec(
                name=f"battery_charge_kw_{t}", time_step=t,
                lower_bound=0.0, upper_bound=energy.max_battery_charge_kw,
                unit="kW", description="Battery charging power",
            ))
            specs.append(DecisionVariableSpec(
                name=f"battery_discharge_kw_{t}", time_step=t,
                lower_bound=0.0, upper_bound=energy.max_battery_discharge_kw,
                unit="kW", description="Battery discharging power",
            ))
            specs.append(DecisionVariableSpec(
                name=f"battery_soc_{t}", time_step=t,
                lower_bound=0.15, upper_bound=0.95,
                unit="fraction", description="Battery state of charge",
            ))

            # Hydrogen variables
            specs.append(DecisionVariableSpec(
                name=f"hydrogen_charge_kw_{t}", time_step=t,
                lower_bound=0.0, upper_bound=energy.max_hydrogen_charge_kw,
                unit="kW", description="Electrolyzer input power",
            ))
            specs.append(DecisionVariableSpec(
                name=f"hydrogen_discharge_kw_{t}", time_step=t,
                lower_bound=0.0, upper_bound=energy.max_hydrogen_discharge_kw,
                unit="kW", description="Fuel cell output power",
            ))

            # Curtailment
            specs.append(DecisionVariableSpec(
                name=f"curtailment_kw_{t}", time_step=t,
                lower_bound=0.0, upper_bound=float("inf"),
                unit="kW", description="Renewable curtailment",
            ))

        # Mission variables
        for m in request.missions:
            for t in range(n_steps):
                specs.append(DecisionVariableSpec(
                    name=f"mission_power_{m.mission_id}_{t}", time_step=t,
                    lower_bound=0.0, upper_bound=m.max_power_kw,
                    unit="kW", description=f"Power allocated to mission {m.name}",
                ))
                specs.append(DecisionVariableSpec(
                    name=f"mission_active_{m.mission_id}_{t}", time_step=t,
                    var_type=VariableType.BINARY,
                    lower_bound=0, upper_bound=1,
                    unit="binary", description=f"Whether mission {m.name} is active",
                ))

        return specs

    @staticmethod
    def build_initial_conditions_summary(request: OptimizationRequest) -> Dict[str, Any]:
        """Summarize initial conditions for audit trail."""
        energy = request.energy_state
        batt_cap = energy.battery_capacity_kwh * energy.battery_soh

        return {
            "battery_soc_initial": energy.battery_soc,
            "battery_energy_kwh_initial": energy.battery_soc * batt_cap,
            "battery_capacity_kwh_effective": batt_cap,
            "hydrogen_energy_kwh_initial": energy.hydrogen_energy_kwh,
            "hydrogen_tank_capacity_kwh": energy.hydrogen_tank_capacity_kwh,
            "current_solar_kw": energy.current_solar_kw,
            "current_wind_kw": energy.current_wind_kw,
            "current_load_kw": energy.current_load_kw,
            "mission_count": len(request.missions),
            "equipment_count": len(request.equipment),
            "required_reserve_kwh": request.reserve.required_reserve_kwh,
        }
