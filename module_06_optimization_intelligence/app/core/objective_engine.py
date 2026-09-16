"""
Objective Engine.

Formulates weighted multi-objective targets and calculates objective term breakdowns.
All objective weights are configurable and transparently documented.
"""

from __future__ import annotations

from typing import Dict, Any
from app.config.settings import Settings
from app.models.optimization_request import OptimizationRequest, MissionPriority


class ObjectiveEngine:
    """Computes transparent objective value breakdowns post-optimization."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def calculate_objective_breakdown(
        self,
        request: OptimizationRequest,
        var_values: Dict[str, Any]
    ) -> Dict[str, float]:
        """Compute detailed breakdown of objective components."""
        if not var_values:
            return {}

        dt_hours = var_values.get("dt_hours", 1.0)
        n_steps = var_values.get("n_steps", 1)

        # Priority weights
        p_weights = {
            MissionPriority.P0: 100000.0,
            MissionPriority.P1: 10000.0,
            MissionPriority.P2: 1000.0,
            MissionPriority.P3: 100.0,
            MissionPriority.P4: 10.0,
        }

        # 1. Mission Completion Value
        mission_completion_value = 0.0
        missions_dict = var_values.get("missions", {})
        
        for m in request.missions:
            weight = p_weights.get(m.priority, 100.0)
            if m.mission_id in missions_dict:
                powers = missions_dict[m.mission_id].get("power_kw", [])
                total_energy = sum(powers) * dt_hours
                mission_completion_value += total_energy * weight

        # 2. Renewable Utilization Value
        solar_f = var_values.get("solar_f", [0.0] * n_steps)
        wind_f = var_values.get("wind_f", [0.0] * n_steps)
        curtailment = var_values.get("curtailment", [0.0] * n_steps)
        
        total_gen = sum(solar_f) + sum(wind_f)
        total_curtailed = sum(curtailment)
        used_renewable = max(0.0, total_gen - total_curtailed)
        renewable_utilization_value = used_renewable * self.settings.weight_renewable_utilization

        # 3. Penalties
        curtailment_penalty = total_curtailed * self.settings.penalty_renewable_curtailment
        
        batt_chg = sum(var_values.get("batt_charge", []))
        batt_dis = sum(var_values.get("batt_discharge", []))
        battery_cycling_penalty = (batt_chg + batt_dis) * dt_hours * self.settings.penalty_battery_cycling

        h2_dis = sum(var_values.get("h2_discharge", []))
        hydrogen_penalty = h2_dis * dt_hours * self.settings.penalty_hydrogen_consumption

        total_objective = (
            mission_completion_value
            + renewable_utilization_value
            - curtailment_penalty
            - battery_cycling_penalty
            - hydrogen_penalty
        )

        return {
            "total_objective": round(total_objective, 2),
            "mission_completion_value": round(mission_completion_value, 2),
            "renewable_utilization_value": round(renewable_utilization_value, 2),
            "curtailment_penalty": round(curtailment_penalty, 2),
            "battery_cycling_penalty": round(battery_cycling_penalty, 2),
            "hydrogen_consumption_penalty": round(hydrogen_penalty, 2),
        }
