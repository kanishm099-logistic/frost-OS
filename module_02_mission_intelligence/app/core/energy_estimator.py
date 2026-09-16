"""
Frost OS Module 02 — Energy Estimator & Power Boundary Enforcer.

Calculates actual cumulative energy usage (kWh) and strictly enforces
the minimum safe operating power threshold (min_power_kw).
"""

from __future__ import annotations

from app.models.energy_requirement import EnergyRequirement
from app.models.mission import Flexibility, Mission


class EnergyEstimator:
    """Calculates mission energy requirements and validates power boundaries."""

    @staticmethod
    def calculate_base_energy(
        power_kw: float,
        duration_minutes: int,
        utilization_factor: float = 1.0,
    ) -> float:
        """
        Calculate base electrical energy in kWh:
        energy_kwh = power_kw * (duration_minutes / 60) * utilization_factor
        """
        if power_kw <= 0:
            raise ValueError(f"Power must be positive, got {power_kw} kW")
        if duration_minutes <= 0:
            raise ValueError(f"Duration must be positive, got {duration_minutes} minutes")
        if not (0.0 < utilization_factor <= 1.0):
            raise ValueError(f"Utilization factor must be in (0, 1], got {utilization_factor}")

        duration_hours = duration_minutes / 60.0
        return round(power_kw * duration_hours * utilization_factor, 3)

    @staticmethod
    def validate_power_allocation(mission: Mission, proposed_kw: float) -> tuple[bool, str]:
        """
        Validate whether a proposed power allocation respects mission physical constraints.

        CRITICAL SAFETY RULE:
        If a mission requires min_power_kw (e.g. 90 kW), it MUST NOT be assigned less
        (e.g. 70 kW) merely because energy is scarce. It must either be operated at or above
        min_power_kw, or safely paused/stopped (0 kW).
        """
        # Complete shutdown / pause is allowed if workload permits
        if proposed_kw == 0.0:
            if mission.flexibility == Flexibility.INFLEXIBLE:
                return (
                    False,
                    f"Workload '{mission.name}' is INFLEXIBLE and cannot be shut down.",
                )
            return (True, f"Workload '{mission.name}' can be safely paused/stopped (0 kW).")

        # Allocation below minimum safe threshold is STRICTLY FORBIDDEN
        if proposed_kw < mission.min_power_kw:
            return (
                False,
                f"SAFETY VIOLATION: Proposed allocation {proposed_kw} kW is below minimum safe operating "
                f"threshold ({mission.min_power_kw} kW) for '{mission.name}'. Workload must either receive "
                f">= {mission.min_power_kw} kW, be delayed, or safely stopped.",
            )

        # Allocation above maximum threshold
        if proposed_kw > mission.max_power_kw:
            return (
                False,
                f"Proposed allocation {proposed_kw} kW exceeds maximum rating ({mission.max_power_kw} kW) "
                f"for '{mission.name}'.",
            )

        return (
            True,
            f"Proposed allocation {proposed_kw} kW is within safe operating range "
            f"[{mission.min_power_kw} kW, {mission.max_power_kw} kW].",
        )

    @staticmethod
    def calculate_curtailment_potential(mission: Mission) -> float:
        """
        Calculate how much power (kW) this mission can voluntarily shed
        while still operating at or above min_power_kw.
        """
        if mission.flexibility in (Flexibility.PARTIALLY_FLEXIBLE, Flexibility.FLEXIBLE):
            return max(0.0, round(mission.required_power_kw - mission.min_power_kw, 2))
        return 0.0
