"""
Plan Generator.

Translates solver decision variables into structured OptimizationResult payloads
and high-level operational ActionPlan proposals for Module 01 Orchestrator.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from app.models.optimization_request import OptimizationRequest
from app.models.optimization_result import (
    OptimizationResult,
    MissionAllocationItem,
    StorageScheduleItem,
    ReserveTrajectoryItem,
)
from app.models.action_plan import ActionPlan, ActionItem, ActionType
from app.models.constraint import ConstraintViolation


class PlanGenerator:
    """Generates structured optimization outputs and actionable operational plans."""

    @staticmethod
    def generate_result(
        request: OptimizationRequest,
        solver_name: str,
        solver_status: str,
        objective_value: float,
        var_values: Dict[str, Any],
        is_valid: bool,
        violations: List[ConstraintViolation],
        objective_breakdown: Dict[str, float],
        solve_time_seconds: float = 0.0
    ) -> OptimizationResult:
        """Construct complete OptimizationResult."""
        opt_id = f"OPT-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()

        n_steps = var_values.get("n_steps", 0)
        dt_mins = var_values.get("dt_minutes", request.time_step_minutes)
        dt_hours = var_values.get("dt_hours", dt_mins / 60.0)

        batt_chg = var_values.get("batt_charge", [0.0] * n_steps)
        batt_dis = var_values.get("batt_discharge", [0.0] * n_steps)
        batt_soc = var_values.get("batt_soc", [0.0] * n_steps)

        h2_chg = var_values.get("h2_charge", [0.0] * n_steps)
        h2_dis = var_values.get("h2_discharge", [0.0] * n_steps)
        h2_kwh = var_values.get("h2_kwh", [0.0] * n_steps)

        solar_f = var_values.get("solar_f", [0.0] * n_steps)
        wind_f = var_values.get("wind_f", [0.0] * n_steps)
        curtailment = var_values.get("curtailment", [0.0] * n_steps)
        missions_dict = var_values.get("missions", {})

        batt_cap = request.energy_state.battery_capacity_kwh * request.energy_state.battery_soh
        req_reserve = request.reserve.required_reserve_kwh

        # Build Mission Allocations
        mission_allocations = []
        for m in request.missions:
            powers = missions_dict.get(m.mission_id, {}).get("power_kw", [0.0] * n_steps)
            actives = missions_dict.get(m.mission_id, {}).get("active", [False] * n_steps)
            
            cum_e = 0.0
            for t in range(n_steps):
                p = powers[t] if t < len(powers) else 0.0
                act = actives[t] if t < len(actives) else False
                cum_e += p * dt_hours
                
                mission_allocations.append(
                    MissionAllocationItem(
                        mission_id=m.mission_id,
                        mission_name=m.name,
                        priority=m.priority.value if hasattr(m.priority, "value") else str(m.priority),
                        time_step=t,
                        time_minutes=t * dt_mins,
                        allocated_power_kw=round(p, 2),
                        is_active=act,
                        cumulative_energy_kwh=round(cum_e, 2),
                        satisfied=cum_e >= (m.energy_required_kwh - 0.1),
                    )
                )

        # Build Storage Schedules
        storage_schedules = []
        for t in range(n_steps):
            c_batt = batt_chg[t] if t < len(batt_chg) else 0.0
            d_batt = batt_dis[t] if t < len(batt_dis) else 0.0
            soc_b = batt_soc[t] if t < len(batt_soc) else 0.0

            c_h2 = h2_chg[t] if t < len(h2_chg) else 0.0
            d_h2 = h2_dis[t] if t < len(h2_dis) else 0.0
            e_h2 = h2_kwh[t] if t < len(h2_kwh) else 0.0

            storage_schedules.append(
                StorageScheduleItem(
                    time_step=t,
                    time_minutes=t * dt_mins,
                    battery_charge_kw=round(c_batt, 2),
                    battery_discharge_kw=round(d_batt, 2),
                    battery_soc=round(soc_b, 4),
                    battery_energy_kwh=round(soc_b * batt_cap, 2),
                    hydrogen_charge_kw=round(c_h2, 2),
                    hydrogen_discharge_kw=round(d_h2, 2),
                    hydrogen_energy_kwh=round(e_h2, 2),
                )
            )

        # Build Generation Schedule
        gen_schedule = []
        for t in range(n_steps):
            sol = solar_f[t] if t < len(solar_f) else 0.0
            wnd = wind_f[t] if t < len(wind_f) else 0.0
            gen_schedule.append(
                {
                    "time_step": t,
                    "time_minutes": t * dt_mins,
                    "solar_kw": round(sol, 2),
                    "wind_kw": round(wnd, 2),
                    "total_renewable_kw": round(sol + wnd, 2),
                }
            )

        # Build Reserve Trajectories
        reserve_trajectories = []
        for t in range(n_steps):
            soc_b = batt_soc[t] if t < len(batt_soc) else 0.0
            e_h2 = h2_kwh[t] if t < len(h2_kwh) else 0.0
            total_stored = soc_b * batt_cap + e_h2

            reserve_trajectories.append(
                ReserveTrajectoryItem(
                    time_step=t,
                    time_minutes=t * dt_mins,
                    projected_stored_energy_kwh=round(total_stored, 2),
                    required_reserve_kwh=req_reserve,
                    protected_energy_kwh=request.reserve.protected_energy_kwh,
                    margin_kwh=round(total_stored - req_reserve, 2),
                    reserve_met=total_stored >= req_reserve,
                )
            )

        # Generate ActionPlan
        action_plan = PlanGenerator._build_action_plan(
            request=request,
            opt_id=opt_id,
            now_iso=now_iso,
            var_values=var_values,
            is_valid=is_valid,
        )

        explanations = PlanGenerator._generate_explanations(request, mission_allocations, storage_schedules)

        return OptimizationResult(
            optimization_id=opt_id,
            station_id=request.station_id,
            created_at=now_iso,
            horizon_minutes=request.horizon_minutes,
            time_step_minutes=dt_mins,
            solve_time_seconds=round(solve_time_seconds, 3),
            objective_value=round(objective_value, 2),
            solver=solver_name,
            solver_status=solver_status,
            feasible=solver_status in ["OPTIMAL", "FEASIBLE"] and is_valid,
            validation_passed=is_valid,
            constraint_summary={"total": n_steps * 4, "satisfied": n_steps * 4 - len(violations), "violated": len(violations)},
            violations=violations,
            mission_allocations=mission_allocations,
            storage_schedule=storage_schedules,
            generation_schedule=gen_schedule,
            curtailment=[round(c, 2) for c in curtailment],
            reserve_trajectory=reserve_trajectories,
            scenario=request.scenario.value if hasattr(request.scenario, "value") else str(request.scenario),
            objective_breakdown=objective_breakdown,
            explanations=explanations,
            action_plan=action_plan if is_valid else None,
            model_version="1.0.0",
        )

    @staticmethod
    def _build_action_plan(
        request: OptimizationRequest,
        opt_id: str,
        now_iso: str,
        var_values: Dict[str, Any],
        is_valid: bool
    ) -> ActionPlan:
        """Create ActionPlan structure with high-level operational commands for M01."""
        actions: List[ActionItem] = []
        n_steps = var_values.get("n_steps", 0)
        dt_mins = var_values.get("dt_minutes", request.time_step_minutes)
        missions_dict = var_values.get("missions", {})

        batt_chg = var_values.get("batt_charge", [0.0] * n_steps)
        batt_dis = var_values.get("batt_discharge", [0.0] * n_steps)

        # 1. Mission Actions
        for m in request.missions:
            powers = missions_dict.get(m.mission_id, {}).get("power_kw", [0.0] * n_steps)
            actives = missions_dict.get(m.mission_id, {}).get("active", [False] * n_steps)

            was_active = False
            for t in range(n_steps):
                p = powers[t] if t < len(powers) else 0.0
                act = actives[t] if t < len(actives) else False
                
                if act and not was_active:
                    actions.append(
                        ActionItem(
                            action_id=f"ACT-START-{m.mission_id}-{t}",
                            action_type=ActionType.START_MISSION,
                            target_entity_id=m.mission_id,
                            time_step=t,
                            start_time_minutes=t * dt_mins,
                            power_kw=round(p, 2),
                            priority=str(m.priority),
                            rationale=f"Initiate mission {m.name} under available energy budget",
                        )
                    )
                elif not act and was_active:
                    actions.append(
                        ActionItem(
                            action_id=f"ACT-PAUSE-{m.mission_id}-{t}",
                            action_type=ActionType.PAUSE_MISSION,
                            target_entity_id=m.mission_id,
                            time_step=t,
                            start_time_minutes=t * dt_mins,
                            priority=str(m.priority),
                            rationale=f"Pause mission {m.name} to preserve power / reserve",
                        )
                    )
                was_active = act

        # 2. Storage Actions (Immediate step t=0)
        if n_steps > 0:
            c0 = batt_chg[0] if len(batt_chg) > 0 else 0.0
            d0 = batt_dis[0] if len(batt_dis) > 0 else 0.0
            
            if c0 > 1.0:
                actions.append(
                    ActionItem(
                        action_id="ACT-BATT-CHG-0",
                        action_type=ActionType.CHARGE_BATTERY,
                        target_entity_id="BESS-PRIMARY",
                        time_step=0,
                        start_time_minutes=0,
                        power_kw=round(c0, 2),
                        rationale="Charge battery using renewable surplus",
                    )
                )
            elif d0 > 1.0:
                actions.append(
                    ActionItem(
                        action_id="ACT-BATT-DIS-0",
                        action_type=ActionType.DISCHARGE_BATTERY,
                        target_entity_id="BESS-PRIMARY",
                        time_step=0,
                        start_time_minutes=0,
                        power_kw=round(d0, 2),
                        rationale="Discharge battery to meet station load & mission demand",
                    )
                )

        return ActionPlan(
            plan_id=f"PLAN-{uuid.uuid4().hex[:8].upper()}",
            optimization_id=opt_id,
            station_id=request.station_id,
            created_at=now_iso,
            horizon_minutes=request.horizon_minutes,
            time_step_minutes=dt_mins,
            status="PROPOSED" if is_valid else "REJECTED",
            is_executable=is_valid,
            actions=actions,
            summary=f"ActionPlan generated with {len(actions)} operational items",
        )

    @staticmethod
    def _generate_explanations(
        request: OptimizationRequest,
        allocations: List[MissionAllocationItem],
        schedules: List[StorageScheduleItem]
    ) -> List[str]:
        """Generate human-readable explanations for optimization trade-offs."""
        exps = []
        exps.append(f"Optimization completed for station '{request.station_id}' over {request.horizon_minutes}m horizon.")
        
        # Check active missions count
        active_ids = {a.mission_id for a in allocations if a.is_active}
        total_missions = len(request.missions)
        exps.append(f"Scheduled {len(active_ids)} out of {total_missions} missions based on priority weights.")

        # Check storage activity
        if schedules:
            soc_end = schedules[-1].battery_soc
            exps.append(f"Projected end-of-horizon battery SOC is {soc_end*100:.1f}%.")

        return exps
