"""
Frost OS Module 02 — Mission Energy Buffer Engine.

Calculates protective energy margins in kWh (NOT electrical current).
Guarantees that critical P0 and P1 workloads have reserved energy buffers
to protect against polar station generator fluctuations or renewable drops.
"""

from __future__ import annotations

from app.config.settings import Settings
from app.models.priority import PriorityLevel


class BufferEngine:
    """Calculates protective energy reserves (kWh) for station missions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_buffer_factor(self, priority: PriorityLevel) -> float:
        """Get the configured buffer factor for a priority level."""
        factors = {
            PriorityLevel.P0: self.settings.buffer_factor_p0,
            PriorityLevel.P1: self.settings.buffer_factor_p1,
            PriorityLevel.P2: self.settings.buffer_factor_p2,
            PriorityLevel.P3: self.settings.buffer_factor_p3,
            PriorityLevel.P4: self.settings.buffer_factor_p4,
        }
        return factors.get(priority, 0.0)

    def calculate_buffer(
        self,
        priority: PriorityLevel,
        base_energy_kwh: float,
        custom_factor: float | None = None,
    ) -> tuple[float, float]:
        """
        Calculate protective energy buffer:
          mission_buffer_kwh = base_energy_kwh * buffer_factor
          protected_energy_kwh = base_energy_kwh + mission_buffer_kwh

        Returns (buffer_kwh, protected_energy_kwh)
        """
        if base_energy_kwh < 0:
            raise ValueError(f"Base energy must be non-negative, got {base_energy_kwh} kWh")

        factor = custom_factor if custom_factor is not None else self.get_buffer_factor(priority)
        if factor < 0.0:
            raise ValueError(f"Buffer factor must be non-negative, got {factor}")

        buffer_kwh = round(base_energy_kwh * factor, 3)
        protected_energy_kwh = round(base_energy_kwh + buffer_kwh, 3)

        return buffer_kwh, protected_energy_kwh
