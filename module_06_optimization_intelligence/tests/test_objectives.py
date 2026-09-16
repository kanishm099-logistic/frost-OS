"""
Unit tests for ObjectiveEngine.
"""

from __future__ import annotations

from app.config.settings import Settings
from app.core.objective_engine import ObjectiveEngine
from app.models.optimization_request import OptimizationRequest


def test_objective_breakdown_calculation(settings: Settings, sample_request: OptimizationRequest):
    """Test objective breakdown formatting."""
    engine = ObjectiveEngine(settings)
    
    mock_vars = {
        "n_steps": 24,
        "dt_hours": 1.0,
        "solar_f": [200.0] * 24,
        "wind_f": [100.0] * 24,
        "curtailment": [10.0] * 24,
        "batt_charge": [5.0] * 24,
        "batt_discharge": [5.0] * 24,
        "h2_discharge": [0.0] * 24,
        "missions": {
            "MIS-LIFE-01": {"power_kw": [100.0] * 24, "active": [True] * 24}
        },
    }

    breakdown = engine.calculate_objective_breakdown(sample_request, mock_vars)

    assert "total_objective" in breakdown
    assert "mission_completion_value" in breakdown
    assert "curtailment_penalty" in breakdown
    assert breakdown["curtailment_penalty"] > 0.0
