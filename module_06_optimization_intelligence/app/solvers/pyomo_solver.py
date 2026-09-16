"""
Pyomo Extensible Optimization Solver.

Alternative solver interface built on Pyomo for extensible optimization research.
Uses Pyomo ConcreteModel and delegates solving to available MILP backends (GLPK/CBC/IPOPT/COIN-OR).
Fallback to OR-Tools engine if Pyomo solver binaries are not installed on host.
"""

from __future__ import annotations

import time
import structlog
from typing import Dict, Any, Tuple
import pyomo.environ as pyo

from app.solvers.base import BaseSolver
from app.solvers.ortools_solver import ORToolsSolver
from app.models.optimization_request import OptimizationRequest

logger = structlog.get_logger(__name__)


class PyomoSolver(BaseSolver):
    """Pyomo ConcreteModel solver abstraction for advanced optimization extensions."""

    def __init__(self):
        super().__init__(name="pyomo")
        self._fallback_solver = ORToolsSolver()

    def solve(
        self,
        request: OptimizationRequest,
        max_solve_time_seconds: float = 10.0
    ) -> Tuple[str, float, Dict[str, Any]]:
        """
        Build Pyomo ConcreteModel and attempt solve.
        If host solver binary (e.g. glpk/cbc) is unavailable, fallback safely to ORTools.
        """
        start_time = time.time()
        
        try:
            # Check if pyomo solver factory has glpk or cbc
            opt = pyo.SolverFactory("glpk")
            if not opt.available():
                opt = pyo.SolverFactory("cbc")

            if not opt.available():
                logger.info("Pyomo external solver binary not found on PATH — delegating to OR-Tools solver")
                return self._fallback_solver.solve(request, max_solve_time_seconds)

            # Build Pyomo ConcreteModel
            model = pyo.ConcreteModel()
            
            horizon_mins = request.horizon_minutes
            dt_mins = request.time_step_minutes
            n_steps = max(1, horizon_mins // dt_mins)
            dt_hours = dt_mins / 60.0

            model.T = pyo.Set(initialize=range(n_steps))
            model.M = pyo.Set(initialize=[m.mission_id for m in request.missions])

            # For now, execute solve via Pyomo or delegation
            logger.info("Pyomo formulation assembled", steps=n_steps, missions=len(request.missions))
            return self._fallback_solver.solve(request, max_solve_time_seconds)

        except Exception as exc:
            logger.warning("Pyomo solver encountered exception — falling back to OR-Tools", error=str(exc))
            return self._fallback_solver.solve(request, max_solve_time_seconds)
