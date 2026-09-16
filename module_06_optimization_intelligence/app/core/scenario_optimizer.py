"""
Scenario Optimizer Engine.

Executes multi-scenario optimization evaluations (BASELINE, LOW_RENEWABLE, HIGH_LOAD,
WIND_COLLAPSE, SOLAR_DROP, STORM, EQUIPMENT_DEGRADATION, BATTERY_DEGRADATION, HYDROGEN_SHORTAGE).
Compares feasibility, reserve consumption, and mission trade-offs across scenarios.
"""

from __future__ import annotations

import copy
import structlog
from typing import Dict, List, Any

from app.models.optimization_request import OptimizationRequest, ScenarioType, ForecastDataInput, EnergyStateInput
from app.models.optimization_result import OptimizationResult
from app.solvers.ortools_solver import ORToolsSolver
from app.core.plan_validator import PlanValidator
from app.core.plan_generator import PlanGenerator
from app.core.objective_engine import ObjectiveEngine
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class ScenarioOptimizer:
    """Multi-scenario optimization evaluator."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.solver = ORToolsSolver()
        self.objective_engine = ObjectiveEngine(settings)

    def run_scenarios(
        self,
        base_request: OptimizationRequest,
        scenarios_to_run: List[ScenarioType] = None
    ) -> Dict[str, OptimizationResult]:
        """
        Run optimization against multiple scenario modifications and return map of results.
        """
        if not scenarios_to_run:
            scenarios_to_run = [
                ScenarioType.BASELINE,
                ScenarioType.LOW_RENEWABLE,
                ScenarioType.HIGH_LOAD,
                ScenarioType.WIND_COLLAPSE,
                ScenarioType.STORM,
            ]

        results: Dict[str, OptimizationResult] = {}

        for sc in scenarios_to_run:
            sc_request = copy.deepcopy(base_request)
            sc_request.scenario = sc

            # Apply Scenario Modifications to Inputs
            self._apply_scenario_modifications(sc_request, sc)

            # Solve
            status, obj_val, var_values = self.solver.solve(
                request=sc_request,
                max_solve_time_seconds=sc_request.max_solve_time_seconds or self.settings.max_solve_time_seconds
            )

            # Validate
            is_valid, violations = PlanValidator.validate_plan(sc_request, var_values)

            # Objective breakdown
            breakdown = self.objective_engine.calculate_objective_breakdown(sc_request, var_values)

            # Generate result
            res = PlanGenerator.generate_result(
                request=sc_request,
                solver_name="ortools",
                solver_status=status,
                objective_value=obj_val,
                var_values=var_values,
                is_valid=is_valid,
                violations=violations,
                objective_breakdown=breakdown,
            )

            results[sc.value] = res

        return results

    def _apply_scenario_modifications(self, req: OptimizationRequest, scenario: ScenarioType) -> None:
        """Modify request inputs according to scenario definition."""
        fc = req.forecast
        e = req.energy_state

        if scenario == ScenarioType.LOW_RENEWABLE:
            fc.solar_forecast_kw = [s * 0.5 for s in fc.solar_forecast_kw]
            fc.wind_forecast_kw = [w * 0.5 for w in fc.wind_forecast_kw]
        elif scenario == ScenarioType.HIGH_LOAD:
            fc.load_forecast_kw = [l * 1.35 for l in fc.load_forecast_kw]
        elif scenario == ScenarioType.WIND_COLLAPSE:
            fc.wind_forecast_kw = [0.0 for _ in fc.wind_forecast_kw]
        elif scenario == ScenarioType.SOLAR_DROP:
            fc.solar_forecast_kw = [0.0 for _ in fc.solar_forecast_kw]
        elif scenario == ScenarioType.STORM:
            fc.solar_forecast_kw = [s * 0.2 for s in fc.solar_forecast_kw]
            fc.wind_forecast_kw = [w * 0.3 for w in fc.wind_forecast_kw]
            fc.load_forecast_kw = [l * 1.40 for l in fc.load_forecast_kw]
        elif scenario == ScenarioType.BATTERY_DEGRADATION:
            e.battery_soh = 0.60
            e.max_battery_charge_kw *= 0.60
            e.max_battery_discharge_kw *= 0.60
        elif scenario == ScenarioType.HYDROGEN_SHORTAGE:
            e.hydrogen_energy_kwh = max(50.0, e.min_protected_hydrogen_kwh)
            e.max_hydrogen_discharge_kw *= 0.20
