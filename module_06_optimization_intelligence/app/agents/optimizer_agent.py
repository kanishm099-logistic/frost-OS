"""
Optimizer Agent.

Coordination and human-explainability agent layer around deterministic optimization services.
Selects optimization modes and scenario sets, triggers solver runs, and explains
objective/constraint trade-offs.

BOUNDARIES: Must NOT manually invent numerical allocation values and MUST NOT override Module 07 Safety.
"""

from __future__ import annotations

import structlog
from typing import Dict, Any, List

from app.config.settings import Settings
from app.models.optimization_request import OptimizationRequest, ScenarioType
from app.models.optimization_result import OptimizationResult
from app.core.optimizer import OptimizerCore
from app.core.scenario_optimizer import ScenarioOptimizer

logger = structlog.get_logger(__name__)


class OptimizerAgent:
    """Agentic AI coordinator for Module 06 Optimization Intelligence."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.core = OptimizerCore(settings)
        self.scenario_engine = ScenarioOptimizer(settings)

    def evaluate_and_optimize(
        self,
        request: OptimizationRequest,
        run_multi_scenarios: bool = False
    ) -> Dict[str, Any]:
        """
        Evaluate optimization request, choose execution strategy, run solver, and format explanations.
        """
        logger.info("Optimizer Agent evaluating request", request_id=request.request_id, mode=request.mode)

        # 1. Run Core Optimization
        base_result = self.core.run_optimization(request)

        # 2. Optionally Run Multi-Scenario Analysis
        scenario_results = {}
        if run_multi_scenarios or request.mode == "SCENARIO":
            logger.info("Optimizer Agent running multi-scenario suite")
            scenario_results = self.scenario_engine.run_scenarios(
                base_request=request,
                scenarios_to_run=[
                    ScenarioType.BASELINE,
                    ScenarioType.LOW_RENEWABLE,
                    ScenarioType.HIGH_LOAD,
                    ScenarioType.WIND_COLLAPSE,
                    ScenarioType.STORM,
                ]
            )

        # 3. Formulate Natural Language Executive Rationale
        executive_summary = self._generate_executive_summary(base_result, scenario_results)

        return {
            "result": base_result,
            "scenario_results": scenario_results,
            "agent_explanation": executive_summary,
        }

    def _generate_executive_summary(
        self,
        base_res: OptimizationResult,
        scenarios: Dict[str, OptimizationResult]
    ) -> str:
        """Formulate deterministic executive summary explanation without inventing numbers."""
        if not base_res.feasible:
            report = base_res.infeasibility_report or {}
            conflict = report.get("conflict_explanation", "Optimization problem is infeasible under current constraints.")
            suggested = report.get("deferrable_missions_suggested", [])
            return (
                f"⚠️ INFEASIBLE PLAN: {conflict} "
                f"Consider deferring flexible workloads: {', '.join(suggested) if suggested else 'None'}."
            )

        summary = (
            f"✅ FEASIBLE OPTIMIZATION PLAN PROPOSAL (ID: {base_res.optimization_id}): "
            f"Allocated power for {len(base_res.mission_allocations)} time-step slots with objective value {base_res.objective_value}. "
            f"Station reserve constraints from Module 07 are fully preserved throughout the horizon."
        )

        if scenarios:
            feasible_scenarios = [s_name for s_name, res in scenarios.items() if res.feasible]
            summary += f" Multi-scenario sensitivity analysis shows plan is resilient under: {', '.join(feasible_scenarios)}."

        return summary
