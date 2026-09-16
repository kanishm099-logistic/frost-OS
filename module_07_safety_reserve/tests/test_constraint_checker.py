"""
Unit tests for Constraint Checker Engine.
"""

from __future__ import annotations

from app.core.constraint_checker import ConstraintChecker
from app.core.reserve_engine import ReserveEngine


def test_battery_soc_violation(settings, sample_proposed_plan, sample_energy_state, sample_missions, sample_forecast, sample_equipment_health):
    checker = ConstraintChecker(settings)
    reserve_engine = ReserveEngine(settings)

    # Set SOC below minimum threshold (15% <= 20%)
    sample_energy_state["battery_soc_pct"] = 12.0

    calc = reserve_engine.calculate_reserve(sample_energy_state, sample_missions, sample_forecast, sample_equipment_health)
    hard_viols, soft_viols = checker.check_all_constraints(sample_proposed_plan, sample_energy_state, calc, sample_equipment_health)

    assert len(hard_viols) > 0
    assert any(v.rule_id == "RULE-SOC-01" for v in hard_viols)
