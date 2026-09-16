"""
Base Solver Interface.

Abstract base class for all optimization solver implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple

from app.models.optimization_request import OptimizationRequest
from app.models.optimization_result import OptimizationResult


class BaseSolver(ABC):
    """Abstract Base Class for optimization solvers in Module 06."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def solve(
        self,
        request: OptimizationRequest,
        max_solve_time_seconds: float = 10.0
    ) -> Tuple[str, float, Dict[str, Any]]:
        """
        Execute optimization solve.

        Returns:
            Tuple of:
            - status (OPTIMAL, FEASIBLE, INFEASIBLE, TIMEOUT, ERROR)
            - objective_value (float)
            - raw_variable_values (Dict[str, float or Dict])
        """
        pass
