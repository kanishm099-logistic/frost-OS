"""
Unit tests for ConstraintEngine.
"""

from __future__ import annotations

from app.models.optimization_request import OptimizationRequest
from app.core.constraint_engine import ConstraintEngine
from app.models.constraint import ConstraintType


def test_constraint_specs_generation(sample_request: OptimizationRequest):
    """Test generating constraint specifications."""
    specs = ConstraintEngine.generate_constraint_specs(sample_request, n_steps=24)
    
    assert len(specs) > 0
    power_balance_specs = [s for s in specs if s.constraint_type == ConstraintType.POWER_BALANCE]
    assert len(power_balance_specs) == 24

    reserve_specs = [s for s in specs if s.constraint_type == ConstraintType.STATION_RESERVE]
    assert len(reserve_specs) == 24
    for r in reserve_specs:
        assert r.lower_bound == sample_request.reserve.required_reserve_kwh
