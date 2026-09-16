"""
Constraint Engine.

Defines and tracks system, mission, energy storage, equipment, and safety reserve constraints.
"""

from __future__ import annotations

from typing import List
from app.models.constraint import ConstraintSpec, ConstraintType
from app.models.optimization_request import OptimizationRequest


class ConstraintEngine:
    """Generates explicit mathematical constraint specifications for model documentation and verification."""

    @staticmethod
    def generate_constraint_specs(request: OptimizationRequest, n_steps: int) -> List[ConstraintSpec]:
        """Generate structured list of constraint specifications."""
        specs = []

        # 1. Power Balance Constraints
        for t in range(n_steps):
            specs.append(
                ConstraintSpec(
                    name=f"power_balance_{t}",
                    time_step=t,
                    constraint_type=ConstraintType.POWER_BALANCE,
                    is_hard=True,
                    lower_bound=0.0,
                    upper_bound=0.0,
                    description=f"Energy generation must equal load, storage charge/discharge, and mission consumption at step {t}",
                )
            )

        # 2. Mission Constraints
        for m in request.missions:
            for t in range(n_steps):
                specs.append(
                    ConstraintSpec(
                        name=f"mission_bounds_{m.mission_id}_{t}",
                        time_step=t,
                        constraint_type=ConstraintType.MISSION_MIN_POWER,
                        is_hard=True,
                        lower_bound=m.min_power_kw,
                        upper_bound=m.max_power_kw,
                        description=f"Mission {m.name} power must lie between min {m.min_power_kw}kW and max {m.max_power_kw}kW when active",
                    )
                )

        # 3. Battery Constraints
        batt_cap = request.energy_state.battery_capacity_kwh * request.energy_state.battery_soh
        for t in range(n_steps):
            specs.append(
                ConstraintSpec(
                    name=f"battery_soc_{t}",
                    time_step=t,
                    constraint_type=ConstraintType.BATTERY_SOC,
                    is_hard=True,
                    lower_bound=0.15 * batt_cap,
                    upper_bound=0.95 * batt_cap,
                    description=f"Battery SOC must stay between 15% and 95% of SOH-adjusted capacity ({batt_cap} kWh)",
                )
            )

        # 4. Station Reserve Constraints (M07 Authority)
        for t in range(n_steps):
            specs.append(
                ConstraintSpec(
                    name=f"station_reserve_{t}",
                    time_step=t,
                    constraint_type=ConstraintType.STATION_RESERVE,
                    is_hard=True,
                    lower_bound=request.reserve.required_reserve_kwh,
                    upper_bound=None,
                    description=f"Total projected stored energy at step {t} must meet or exceed required station reserve ({request.reserve.required_reserve_kwh} kWh)",
                )
            )

        return specs
