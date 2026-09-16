"""
OR-Tools Optimization Solver.

Primary MILP optimization engine implemented via Google OR-Tools pywraplp.
Formulates discrete/continuous energy allocation, battery storage trajectories,
hydrogen dispatch, mission scheduling, and reserve bounds.
"""

from __future__ import annotations

import time
import structlog
from typing import Dict, Any, Tuple, List
from ortools.linear_solver import pywraplp

from app.solvers.base import BaseSolver
from app.models.optimization_request import OptimizationRequest, MissionPriority

logger = structlog.get_logger(__name__)


class ORToolsSolver(BaseSolver):
    """MILP Solver built on Google OR-Tools pywraplp (CBC/SCIP)."""

    def __init__(self):
        super().__init__(name="ortools")

    def solve(
        self,
        request: OptimizationRequest,
        max_solve_time_seconds: float = 10.0
    ) -> Tuple[str, float, Dict[str, Any]]:
        """
        Build and solve MILP optimization problem for given request.
        """
        start_time = time.time()
        
        # 1. Create Solver Instance (CBC or SCIP)
        solver = pywraplp.Solver.CreateSolver("CBC")
        if not solver:
            solver = pywraplp.Solver.CreateSolver("SCIP")
        if not solver:
            logger.error("Failed to instantiate OR-Tools MILP solver")
            return "ERROR", 0.0, {}

        # Set solver timeout
        solver.set_time_limit(int(max_solve_time_seconds * 1000))

        # Time resolution settings
        horizon_mins = request.horizon_minutes
        dt_mins = request.time_step_minutes
        n_steps = max(1, horizon_mins // dt_mins)
        dt_hours = dt_mins / 60.0

        # Subsystem inputs
        missions = request.missions
        energy = request.energy_state
        forecast = request.forecast
        reserve = request.reserve
        equipment = {eq.equipment_id: eq for eq in request.equipment}

        # 2. Extract Generation and Load Forecast Arrays
        solar_f = forecast.solar_forecast_kw if forecast.solar_forecast_kw else [0.0] * n_steps
        wind_f = forecast.wind_forecast_kw if forecast.wind_forecast_kw else [0.0] * n_steps
        base_load_f = forecast.load_forecast_kw if forecast.load_forecast_kw else [0.0] * n_steps

        # Extend arrays if shorter than n_steps
        def _pad(arr: List[float], length: int, default_val: float = 0.0) -> List[float]:
            if len(arr) >= length:
                return arr[:length]
            return arr + [default_val] * (length - len(arr))

        solar_f = _pad(solar_f, n_steps, energy.current_solar_kw)
        wind_f = _pad(wind_f, n_steps, energy.current_wind_kw)
        base_load_f = _pad(base_load_f, n_steps, energy.current_load_kw)

        # 3. Create Decision Variables
        # Battery variables
        batt_charge = {}
        batt_discharge = {}
        batt_soc = {}
        
        # Hydrogen variables
        h2_charge = {}
        h2_discharge = {}
        h2_kwh = {}

        # Renewable curtailment
        curtailment = {}

        # Battery & H2 bounds
        batt_cap = max(10.0, energy.battery_capacity_kwh * energy.battery_soh)
        batt_soc_min = 0.15
        batt_soc_max = 0.95
        max_chg = energy.max_battery_charge_kw
        max_dis = energy.max_battery_discharge_kw

        h2_cap = max(10.0, energy.hydrogen_tank_capacity_kwh)
        max_h2_chg = energy.max_hydrogen_charge_kw
        max_h2_dis = energy.max_hydrogen_discharge_kw

        for t in range(n_steps):
            batt_charge[t] = solver.NumVar(0.0, max_chg, f"batt_chg_{t}")
            batt_discharge[t] = solver.NumVar(0.0, max_dis, f"batt_dis_{t}")
            batt_soc[t] = solver.NumVar(batt_soc_min, batt_soc_max, f"batt_soc_{t}")

            h2_charge[t] = solver.NumVar(0.0, max_h2_chg, f"h2_chg_{t}")
            h2_discharge[t] = solver.NumVar(0.0, max_h2_dis, f"h2_dis_{t}")
            h2_kwh[t] = solver.NumVar(energy.min_protected_hydrogen_kwh, h2_cap, f"h2_kwh_{t}")

            curtailment[t] = solver.NumVar(0.0, solver.infinity(), f"curtail_{t}")

        # Mission Variables
        p_mission = {}    # power in kW
        u_mission = {}    # binary active (0 or 1)
        
        for m in missions:
            for t in range(n_steps):
                p_mission[m.mission_id, t] = solver.NumVar(0.0, m.max_power_kw, f"p_{m.mission_id}_{t}")
                u_mission[m.mission_id, t] = solver.BoolVar(f"u_{m.mission_id}_{t}")

        # 4. Add Constraints

        # Battery Storage Dynamics & Initial Condition
        initial_batt_kwh = energy.battery_soc * batt_cap
        initial_h2_kwh = energy.hydrogen_energy_kwh

        eff_chg = energy.battery_charge_efficiency
        eff_dis = energy.battery_discharge_efficiency
        eff_el = energy.electrolyzer_efficiency
        eff_fc = energy.fuel_cell_efficiency

        for t in range(n_steps):
            prev_batt_kwh = initial_batt_kwh if t == 0 else (batt_soc[t-1] * batt_cap)
            prev_h2_kwh = initial_h2_kwh if t == 0 else h2_kwh[t-1]

            # Battery SOC trajectory constraint:
            # batt_soc[t] * batt_cap = prev_batt_kwh + (chg * eff_chg - dis / eff_dis) * dt
            solver.Add(
                batt_soc[t] * batt_cap == prev_batt_kwh + (batt_charge[t] * eff_chg - batt_discharge[t] / eff_dis) * dt_hours
            )

            # Hydrogen trajectory constraint:
            # h2_kwh[t] = prev_h2_kwh + (h2_chg * eff_el - h2_dis / eff_fc) * dt
            solver.Add(
                h2_kwh[t] == prev_h2_kwh + (h2_charge[t] * eff_el - h2_discharge[t] / eff_fc) * dt_hours
            )

            # M07 Reserve Protection Constraint
            # projected_stored_energy[t] >= required_reserve_kwh[t]
            solver.Add(
                batt_soc[t] * batt_cap + h2_kwh[t] >= reserve.required_reserve_kwh
            )

        # Power Balance Constraint at each time step
        # Solar[t] + Wind[t] + Batt_Discharge[t] + H2_Discharge[t]
        # = BaseLoad[t] + Batt_Charge[t] + H2_Charge[t] + Curtailment[t] + sum_m P_Mission[m, t]
        for t in range(n_steps):
            solar_t = solar_f[t]
            wind_t = wind_f[t]
            
            # Apply M05 Equipment derating if present
            # e.g., if solar/wind equipment is derated
            total_gen_t = solar_t + wind_t

            balance_expr = (
                total_gen_t
                + batt_discharge[t]
                + h2_discharge[t] * eff_fc
                - base_load_f[t]
                - batt_charge[t]
                - h2_charge[t]
                - curtailment[t]
                - solver.Sum([p_mission[m.mission_id, t] for m in missions])
            )
            solver.Add(balance_expr == 0.0)

        # Mission Operating Bounds & Logic Constraints
        for m in missions:
            # 1. Power allocation when active: min_power <= p_mission <= max_power
            # If inactive (u=0), p_mission MUST be 0.
            for t in range(n_steps):
                time_mins = t * dt_mins
                
                # Check earliest start and deadline
                if time_mins < m.earliest_start_minutes or time_mins >= m.deadline_minutes:
                    solver.Add(u_mission[m.mission_id, t] == 0)
                    solver.Add(p_mission[m.mission_id, t] == 0.0)
                else:
                    # Critical logic: min_power * u <= p_mission <= max_power * u
                    min_p = m.min_power_kw
                    if m.has_reduced_power_mode and m.reduced_power_min_kw is not None:
                        min_p = m.reduced_power_min_kw
                        
                    solver.Add(p_mission[m.mission_id, t] >= min_p * u_mission[m.mission_id, t])
                    solver.Add(p_mission[m.mission_id, t] <= m.max_power_kw * u_mission[m.mission_id, t])

            # P0 and P1 Protected Hard Constraint: P0/P1 missions MUST be active and receive energy
            if m.priority in [MissionPriority.P0, MissionPriority.P1]:
                # Require total delivered energy to meet energy_required_kwh
                delivered_energy = solver.Sum([p_mission[m.mission_id, t] * dt_hours for t in range(n_steps)])
                solver.Add(delivered_energy >= m.energy_required_kwh)

        # 5. Formulate Objective Function
        objective = solver.Objective()
        objective.SetMaximization()

        # Priority Weights
        p_weights = {
            MissionPriority.P0: 100000.0,
            MissionPriority.P1: 10000.0,
            MissionPriority.P2: 1000.0,
            MissionPriority.P3: 100.0,
            MissionPriority.P4: 10.0,
        }

        # Maximization Terms
        for m in missions:
            weight = p_weights.get(m.priority, 100.0)
            for t in range(n_steps):
                # Reward delivered power & active status
                objective.SetCoefficient(p_mission[m.mission_id, t], weight * dt_hours)

        # Minimization / Penalty Terms (Curtailed energy, battery cycling, H2 penalty)
        for t in range(n_steps):
            objective.SetCoefficient(curtailment[t], -15.0)
            objective.SetCoefficient(batt_charge[t], -0.5)
            objective.SetCoefficient(batt_discharge[t], -0.5)
            objective.SetCoefficient(h2_discharge[t], -10.0)  # Preserving long-term H2 reserve

        # 6. Solve Model
        status_code = solver.Solve()
        solve_duration = time.time() - start_time

        # Map Solver Status
        status_map = {
            pywraplp.Solver.OPTIMAL: "OPTIMAL",
            pywraplp.Solver.FEASIBLE: "FEASIBLE",
            pywraplp.Solver.INFEASIBLE: "INFEASIBLE",
            pywraplp.Solver.UNBOUNDED: "UNBOUNDED",
            pywraplp.Solver.ABNORMAL: "ERROR",
            pywraplp.Solver.NOT_SOLVED: "TIMEOUT",
        }
        status_str = status_map.get(status_code, "UNKNOWN")

        if status_code not in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
            logger.warning("OR-Tools solver completed with non-feasible status", status=status_str, duration=solve_duration)
            return status_str, 0.0, {}

        # 7. Extract Decision Variable Solution Values
        obj_val = objective.Value()

        var_values = {
            "n_steps": n_steps,
            "dt_minutes": dt_mins,
            "dt_hours": dt_hours,
            "batt_charge": [batt_charge[t].solution_value() for t in range(n_steps)],
            "batt_discharge": [batt_discharge[t].solution_value() for t in range(n_steps)],
            "batt_soc": [batt_soc[t].solution_value() for t in range(n_steps)],
            "h2_charge": [h2_charge[t].solution_value() for t in range(n_steps)],
            "h2_discharge": [h2_discharge[t].solution_value() for t in range(n_steps)],
            "h2_kwh": [h2_kwh[t].solution_value() for t in range(n_steps)],
            "curtailment": [curtailment[t].solution_value() for t in range(n_steps)],
            "missions": {},
            "solar_f": solar_f,
            "wind_f": wind_f,
            "base_load_f": base_load_f,
        }

        for m in missions:
            var_values["missions"][m.mission_id] = {
                "power_kw": [p_mission[m.mission_id, t].solution_value() for t in range(n_steps)],
                "active": [bool(u_mission[m.mission_id, t].solution_value() > 0.5) for t in range(n_steps)],
            }

        logger.info("OR-Tools solver completed successfully", status=status_str, objective_value=obj_val, duration=solve_duration)
        return status_str, obj_val, var_values
