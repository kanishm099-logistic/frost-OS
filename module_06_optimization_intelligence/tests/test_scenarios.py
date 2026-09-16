"""
Unit tests for ScenarioOptimizer.
"""

from __future__ import annotations

from app.config.settings import Settings
from app.models.optimization_request import OptimizationRequest, ScenarioType
from app.core.scenario_optimizer import ScenarioOptimizer


def test_multi_scenario_execution(settings: Settings, sample_request: OptimizationRequest):
    """Test executing multi-scenario suite."""
    sc_optimizer = ScenarioOptimizer(settings)
    
    results = sc_optimizer.run_scenarios(
        base_request=sample_request,
        scenarios_to_run=[ScenarioType.BASELINE, ScenarioType.LOW_RENEWABLE, ScenarioType.STORM]
    )

    assert "BASELINE" in results
    assert "LOW_RENEWABLE" in results
    assert "STORM" in results
    assert results["BASELINE"].feasible is True
