"""
Unit tests for PlanValidator.
"""

from __future__ import annotations

from app.models.optimization_request import OptimizationRequest
from app.core.plan_validator import PlanValidator


def test_validator_detects_imbalance(sample_request: OptimizationRequest):
    """Test PlanValidator flags severe power imbalance."""
    invalid_vars = {
        "n_steps": 1,
        "dt_hours": 1.0,
        "dt_minutes": 60,
        "solar_f": [100.0],
        "wind_f": [0.0],
        "base_load_f": [50.0],
        "batt_charge": [0.0],
        "batt_discharge": [0.0],
        "batt_soc": [0.5],
        "h2_charge": [0.0],
        "h2_discharge": [0.0],
        "h2_kwh": [1000.0],
        "curtailment": [0.0],  # 100kW supply vs 50kW demand -> Imbalance of 50kW!
        "missions": {},
    }

    is_valid, violations = PlanValidator.validate_plan(sample_request, invalid_vars)
    assert is_valid is False
    assert len(violations) > 0
    assert any(v.constraint_name == "power_balance_step_0" for v in violations)


def test_validator_detects_min_power_breach(sample_request: OptimizationRequest):
    """Test PlanValidator flags allocation below min_power_kw."""
    m_id = sample_request.missions[0].mission_id  # MIS-LIFE-01 requires min 100kW!

    invalid_vars = {
        "n_steps": 1,
        "dt_hours": 1.0,
        "dt_minutes": 60,
        "solar_f": [80.0],
        "wind_f": [0.0],
        "base_load_f": [30.0],
        "batt_charge": [0.0],
        "batt_discharge": [0.0],
        "batt_soc": [0.5],
        "h2_charge": [0.0],
        "h2_discharge": [0.0],
        "h2_kwh": [1000.0],
        "curtailment": [0.0],
        "missions": {
            m_id: {"power_kw": [50.0], "active": [True]}  # 50 kW allocated when min is 100 kW!
        },
    }

    is_valid, violations = PlanValidator.validate_plan(sample_request, invalid_vars)
    assert is_valid is False
    assert any(v.affected_entity == m_id for v in violations)
