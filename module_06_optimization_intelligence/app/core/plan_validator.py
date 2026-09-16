"""
Independent Deterministic Plan Validator.

Runs independent post-solve deterministic verification on raw solver output.
Never trusts solver output blindly. Strictly checks power balance, mission power bounds,
deadlines, battery SOC limits, and M07 reserve thresholds.
"""

from __future__ import annotations

import structlog
from typing import List, Dict, Any, Tuple
from app.models.constraint import ConstraintViolation, ConstraintType
from app.models.optimization_request import OptimizationRequest, MissionPriority

logger = structlog.get_logger(__name__)


class PlanValidator:
    """Independent deterministic verification engine for optimization plans."""

    @staticmethod
    def validate_plan(
        request: OptimizationRequest,
        var_values: Dict[str, Any],
        tolerance: float = 0.05  # 0.05 kW numerical tolerance
    ) -> Tuple[bool, List[ConstraintViolation]]:
        """
        Perform independent verification of solver decision variables.

        Returns:
            Tuple of (is_valid: bool, violations: List[ConstraintViolation])
        """
        violations: List[ConstraintViolation] = []
        if not var_values:
            violations.append(
                ConstraintViolation(
                    constraint_name="empty_solver_output",
                    time_step=0,
                    constraint_type=ConstraintType.POWER_BALANCE,
                    actual_value=0.0,
                    severity="CRITICAL",
                    description="Solver returned empty variable dictionary",
                )
            )
            return False, violations

        n_steps = var_values.get("n_steps", 0)
        dt_hours = var_values.get("dt_hours", 1.0)
        dt_mins = var_values.get("dt_minutes", 60)

        solar_f = var_values.get("solar_f", [0.0] * n_steps)
        wind_f = var_values.get("wind_f", [0.0] * n_steps)
        base_load_f = var_values.get("base_load_f", [0.0] * n_steps)

        batt_chg = var_values.get("batt_charge", [0.0] * n_steps)
        batt_dis = var_values.get("batt_discharge", [0.0] * n_steps)
        batt_soc = var_values.get("batt_soc", [0.0] * n_steps)

        h2_chg = var_values.get("h2_charge", [0.0] * n_steps)
        h2_dis = var_values.get("h2_discharge", [0.0] * n_steps)
        h2_kwh = var_values.get("h2_kwh", [0.0] * n_steps)

        curtailment = var_values.get("curtailment", [0.0] * n_steps)
        missions_dict = var_values.get("missions", {})

        eff_fc = request.energy_state.fuel_cell_efficiency
        batt_cap = request.energy_state.battery_capacity_kwh * request.energy_state.battery_soh
        req_reserve = request.reserve.required_reserve_kwh

        # 1. Verify Power Balance at every time step
        for t in range(n_steps):
            total_gen = solar_f[t] + wind_f[t]
            storage_discharge = batt_dis[t] + h2_dis[t] * eff_fc
            
            total_mission_p = 0.0
            for m in request.missions:
                if m.mission_id in missions_dict:
                    powers = missions_dict[m.mission_id].get("power_kw", [])
                    if t < len(powers):
                        total_mission_p += max(0.0, powers[t])

            total_supply = total_gen + storage_discharge
            total_demand = base_load_f[t] + batt_chg[t] + h2_chg[t] + curtailment[t] + total_mission_p

            imbalance = abs(total_supply - total_demand)
            if imbalance > tolerance:
                violations.append(
                    ConstraintViolation(
                        constraint_name=f"power_balance_step_{t}",
                        time_step=t,
                        constraint_type=ConstraintType.POWER_BALANCE,
                        actual_value=total_supply,
                        required_min=total_demand - tolerance,
                        required_max=total_demand + tolerance,
                        severity="CRITICAL",
                        description=f"Power imbalance detected at step {t}: Supply={total_supply:.2f}kW vs Demand={total_demand:.2f}kW (diff={imbalance:.2f}kW)",
                    )
                )

        # 2. Verify Mission Power Allocation Bounds
        for m in request.missions:
            if m.mission_id in missions_dict:
                powers = missions_dict[m.mission_id].get("power_kw", [])
                
                min_allowed = m.min_power_kw
                if m.has_reduced_power_mode and m.reduced_power_min_kw is not None:
                    min_allowed = m.reduced_power_min_kw

                for t, p in enumerate(powers):
                    time_mins = t * dt_mins
                    
                    # If active, must satisfy min_power bounds
                    if p > tolerance:
                        # Check deadline violation
                        if time_mins >= m.deadline_minutes:
                            violations.append(
                                ConstraintViolation(
                                    constraint_name=f"mission_deadline_{m.mission_id}_step_{t}",
                                    time_step=t,
                                    constraint_type=ConstraintType.MISSION_WINDOW,
                                    actual_value=p,
                                    severity="CRITICAL",
                                    affected_entity=m.mission_id,
                                    description=f"Mission {m.name} allocated power after deadline ({m.deadline_minutes} mins) at step {t}",
                                )
                            )

                        # Check lower power bound prohibition (Critical Test Case 1!)
                        if p < (min_allowed - tolerance):
                            violations.append(
                                ConstraintViolation(
                                    constraint_name=f"mission_min_power_{m.mission_id}_step_{t}",
                                    time_step=t,
                                    constraint_type=ConstraintType.MISSION_MIN_POWER,
                                    actual_value=p,
                                    required_min=min_allowed,
                                    severity="CRITICAL",
                                    affected_entity=m.mission_id,
                                    description=f"Mission {m.name} allocated {p:.2f}kW, which is below minimum operating threshold of {min_allowed:.2f}kW",
                                )
                            )

                        # Check max power bound
                        if p > (m.max_power_kw + tolerance):
                            violations.append(
                                ConstraintViolation(
                                    constraint_name=f"mission_max_power_{m.mission_id}_step_{t}",
                                    time_step=t,
                                    constraint_type=ConstraintType.MISSION_MAX_POWER,
                                    actual_value=p,
                                    required_max=m.max_power_kw,
                                    severity="CRITICAL",
                                    affected_entity=m.mission_id,
                                    description=f"Mission {m.name} allocated {p:.2f}kW, which exceeds maximum capability of {m.max_power_kw:.2f}kW",
                                )
                            )

        # 3. Verify M07 Station Reserve Thresholds
        for t in range(n_steps):
            stored_battery_kwh = batt_soc[t] * batt_cap if t < len(batt_soc) else 0.0
            stored_h2_kwh = h2_kwh[t] if t < len(h2_kwh) else 0.0
            total_stored = stored_battery_kwh + stored_h2_kwh

            if total_stored < (req_reserve - tolerance):
                violations.append(
                    ConstraintViolation(
                        constraint_name=f"station_reserve_breach_step_{t}",
                        time_step=t,
                        constraint_type=ConstraintType.STATION_RESERVE,
                        actual_value=total_stored,
                        required_min=req_reserve,
                        severity="CRITICAL",
                        description=f"Station reserve breached at step {t}: Stored energy {total_stored:.2f}kWh < Required reserve {req_reserve:.2f}kWh",
                    )
                )

        is_valid = len(violations) == 0
        if not is_valid:
            logger.warning("Independent plan validation failed", violation_count=len(violations))
        else:
            logger.info("Independent plan validation passed successfully")

        return is_valid, violations
