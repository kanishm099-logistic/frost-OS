"""
Frost OS Module 03 — Power Calculator & Energy Integrator.

Calculates instantaneous net power balances and numerically integrates
energy (kWh) over irregular timestamp intervals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.energy_state import EnergyStatus, GenerationBreakdown


class PowerCalculator:
    """Calculates power balance and integrates cumulative energy."""

    @classmethod
    def calculate_net_power(
        cls,
        generation_kw: float,
        arg2: float = 0.0,
        storage_discharge_kw: float | None = None,
        external_import_kw: float = 0.0,
        load_kw: float | None = None,
        storage_charge_kw: float = 0.0,
        external_export_kw: float = 0.0,
    ) -> float:
        """
        Calculate instantaneous net power balance:
          net_power_kw = (generation + discharge + import) - (load + charge + export)

        Supports both positional call: calculate_net_power(gen_kw, load_kw)
        and full keyword signature: calculate_net_power(generation_kw=..., storage_discharge_kw=..., ...)
        """
        if load_kw is None:
            # Called positionally as (gen_kw, load_kw)
            effective_load_kw = arg2
            effective_discharge_kw = storage_discharge_kw or 0.0
        else:
            effective_load_kw = load_kw
            effective_discharge_kw = storage_discharge_kw if storage_discharge_kw is not None else arg2

        inflow = generation_kw + effective_discharge_kw + external_import_kw
        outflow = effective_load_kw + storage_charge_kw + external_export_kw
        return round(inflow - outflow, 3)

    @staticmethod
    def build_generation_breakdown(sources: list[dict[str, Any]]) -> GenerationBreakdown:
        """Aggregate list of generation sources into GenerationBreakdown."""
        solar = 0.0
        wind = 0.0
        other = 0.0
        for s in sources:
            stype = str(s.get("type", "")).lower()
            p = float(s.get("power_kw", s.get("power", 0.0)))
            if "solar" in stype or "pv" in stype:
                solar += p
            elif "wind" in stype or "turbine" in stype:
                wind += p
            else:
                other += p
        total = solar + wind + other
        return GenerationBreakdown(
            solar=solar,
            wind=wind,
            other=other,
            total=total,
        )

    @staticmethod
    def determine_energy_status(net_power_kw: float, tolerance_kw: float = 1.0) -> EnergyStatus:
        """Categorize power balance into operational status."""
        if net_power_kw > tolerance_kw:
            return EnergyStatus.SURPLUS
        if net_power_kw < -tolerance_kw:
            return EnergyStatus.DEFICIT
        return EnergyStatus.BALANCED

    @staticmethod
    def integrate_energy(
        previous_cumulative_kwh: float,
        power_kw: float,
        delta_seconds: float,
    ) -> float:
        """
        Numerically integrate instantaneous power over time delta:
          delta_kwh = power_kw * (delta_seconds / 3600.0)
          new_cumulative_kwh = previous_cumulative_kwh + delta_kwh
        """
        if delta_seconds <= 0:
            return previous_cumulative_kwh

        delta_hours = delta_seconds / 3600.0
        delta_energy_kwh = power_kw * delta_hours
        return round(previous_cumulative_kwh + delta_energy_kwh, 4)

    @staticmethod
    def integrate_energy_kwh(powers: list[float], timestamps: list[datetime]) -> float:
        """
        Trapezoidal numerical integration of power (kW) over irregular timestamps.
        Returns total energy in kWh.
        """
        if len(powers) < 2 or len(timestamps) < 2:
            return 0.0
        total_kwh = 0.0
        for i in range(len(powers) - 1):
            t1 = timestamps[i]
            t2 = timestamps[i + 1]
            dt_hours = abs((t2 - t1).total_seconds()) / 3600.0
            avg_power = (powers[i] + powers[i + 1]) / 2.0
            total_kwh += avg_power * dt_hours
        return round(total_kwh, 4)
