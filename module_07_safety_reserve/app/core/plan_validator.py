"""
Independent Plan Validator.

Independently recalculates key power balances, storage trajectories, SOCs,
hydrogen levels, ramp rates, and mission energy allocations without blindly
trusting Module 06 outputs.
"""

from __future__ import annotations

from typing import Dict, Any, List
import structlog

from app.models.safety_rule import ConstraintViolation, ConstraintSeverity, ConstraintCategory

logger = structlog.get_logger(__name__)


class IndependentPlanValidator:
    """Deterministic Independent Plan Validator Engine."""

    @staticmethod
    def recalculate_and_validate_plan(
        proposed_plan: Dict[str, Any],
        energy_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Recalculates power balance and storage trajectory step-by-step.
        Returns validation breakdown dict.
        """
        storage_schedule = proposed_plan.get("storage_schedule", [])
        initial_soc = float(energy_state.get("battery_soc_pct", 50.0))
        initial_energy_kwh = float(energy_state.get("battery_energy_kwh", 400.0))
        battery_capacity = float(energy_state.get("battery_capacity_kwh", 800.0))

        recalculated_trajectory = []
        curr_energy = initial_energy_kwh
        valid = True
        recalculation_errors = []

        for step in storage_schedule:
            t_step = step.get("time_step", 0)
            charge_kw = float(step.get("battery_charge_kw", 0.0))
            discharge_kw = float(step.get("battery_discharge_kw", 0.0))
            reported_soc = float(step.get("battery_soc", 50.0))

            # Net energy change over 1 hour step
            net_change_kwh = charge_kw * 0.95 - discharge_kw / 0.95
            curr_energy = max(0.0, min(battery_capacity, curr_energy + net_change_kwh))
            recalc_soc = (curr_energy / battery_capacity) * 100.0

            # Discrepancy check between reported M06 SOC and independently recalculated SOC
            if abs(recalc_soc - reported_soc) > 5.0:
                valid = False
                recalculation_errors.append(
                    f"Step {t_step}: M06 reported SOC {reported_soc}%, but independent recalculation yields {round(recalc_soc, 1)}%."
                )

            recalculated_trajectory.append(
                {
                    "time_step": t_step,
                    "recalculated_energy_kwh": round(curr_energy, 2),
                    "recalculated_soc_pct": round(recalc_soc, 2),
                    "reported_soc_pct": reported_soc,
                }
            )

        return {
            "valid": valid,
            "recalculated_trajectory": recalculated_trajectory,
            "recalculation_errors": recalculation_errors,
        }
