"""
Central Optimizer Coordinator.

Coordinates model building, solver dispatch, timeout management, independent validation,
and fallback infeasibility report generation.
"""

from __future__ import annotations

import time
import structlog
from typing import Dict, Any, Optional

from app.config.settings import Settings
from app.models.optimization_request import OptimizationRequest, MissionPriority
from app.models.optimization_result import OptimizationResult
from app.solvers.base import BaseSolver
from app.solvers.ortools_solver import ORToolsSolver
from app.solvers.pyomo_solver import PyomoSolver
from app.core.plan_validator import PlanValidator
from app.core.plan_generator import PlanGenerator
from app.core.objective_engine import ObjectiveEngine

logger = structlog.get_logger(__name__)


class OptimizerCore:
    """Central decision coordinator for Module 06 Optimization Intelligence."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.ortools_solver = ORToolsSolver()
        self.pyomo_solver = PyomoSolver()
        self.objective_engine = ObjectiveEngine(settings)

    def run_optimization(self, request: OptimizationRequest) -> OptimizationResult:
        """
        Execute full optimization workflow for given request.

        Workflow:
        1. Select solver (OR-Tools or Pyomo)
        2. Set timeout bounds
        3. Solve model
        4. Perform independent deterministic validation
        5. Generate OptimizationResult & ActionPlan proposal
        6. Build infeasibility conflict explanation if unfeasible/invalid
        """
        start_time = time.time()
        logger.info("Initiating Module 06 Optimization Run", request_id=request.request_id, station_id=request.station_id)

        # 1. Select Solver
        solver_name = request.solver_name or self.settings.default_solver
        solver: BaseSolver = self.ortools_solver if solver_name.lower() == "ortools" else self.pyomo_solver

        timeout = request.max_solve_time_seconds or self.settings.max_solve_time_seconds

        # 2. Solve Model
        status_str, obj_val, var_values = solver.solve(request, max_solve_time_seconds=timeout)
        solve_duration = time.time() - start_time

        # 3. Independent Validation
        is_valid, violations = PlanValidator.validate_plan(request, var_values)

        # 4. Objective Breakdown
        breakdown = self.objective_engine.calculate_objective_breakdown(request, var_values)

        # 5. Handle Infeasibility Case
        infeasibility_report = None
        if not is_valid or status_str in ["INFEASIBLE", "ERROR", "TIMEOUT"]:
            infeasibility_report = self._build_infeasibility_report(request, status_str, violations)

        # 6. Generate Result Payload
        result = PlanGenerator.generate_result(
            request=request,
            solver_name=solver.name,
            solver_status=status_str,
            objective_value=obj_val,
            var_values=var_values,
            is_valid=is_valid,
            violations=violations,
            objective_breakdown=breakdown,
            solve_time_seconds=solve_duration,
        )

        if infeasibility_report:
            result.infeasibility_report = infeasibility_report
            result.feasible = False

        logger.info("Optimization run complete", result_id=result.optimization_id, status=result.solver_status, valid=is_valid)
        return result

    def _build_infeasibility_report(
        self,
        request: OptimizationRequest,
        status: str,
        violations: Any
    ) -> Dict[str, Any]:
        """Generate structured infeasibility report with conflict explanations and deferral suggestions."""
        deferrable_missions = [
            m.name for m in request.missions
            if m.priority in [MissionPriority.P2, MissionPriority.P3, MissionPriority.P4] and m.shiftability
        ]

        conflict_explanation = (
            "Available renewable generation and stored battery/hydrogen energy cannot satisfy "
            "P0/P1 mission energy requirements and required station reserve simultaneously."
        )

        return {
            "status": status,
            "conflict_explanation": conflict_explanation,
            "deferrable_missions_suggested": deferrable_missions,
            "violations_detected": len(violations) if violations else 0,
            "recommendation": "Defer non-critical P3/P4 workloads or request temporary M07 reserve threshold adjustment.",
        }
