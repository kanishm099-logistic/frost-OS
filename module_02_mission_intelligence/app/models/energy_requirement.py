"""
Frost OS Module 02 — Energy and Power Requirements.

Distinguishes instantaneous power (kW) from integrated energy (kWh).
Enforces minimum safe operating power thresholds and validates load envelopes.
"""

from __future__ import annotations

import enum
from pydantic import BaseModel, Field, model_validator


class PowerProfileType(str, enum.Enum):
    """Temporal profile of mission power consumption."""
    CONSTANT = "CONSTANT"      # Flat power draw throughout duration
    VARIABLE = "VARIABLE"      # Fluctuates within min/max bounds based on utilization
    PULSED = "PULSED"          # Periodic bursts of power
    STEPPED = "STEPPED"        # Discrete power stages


class PowerRequirement(BaseModel):
    """
    Instantaneous electrical power envelope (kW).

    CRITICAL: min_power_kw is the absolute lower boundary for safe operation.
    A mission MUST NOT be assigned less than min_power_kw during operation.
    """
    nominal_kw: float = Field(..., gt=0.0, description="Nominal operating power in kW")
    min_power_kw: float = Field(..., gt=0.0, description="Minimum safe operating power in kW")
    max_power_kw: float = Field(..., gt=0.0, description="Maximum peak power draw in kW")
    profile_type: PowerProfileType = Field(
        default=PowerProfileType.CONSTANT,
        description="Power draw characteristic",
    )
    utilization_factor: float = Field(
        default=1.0,
        gt=0.0,
        le=1.0,
        description="Average duty cycle or utilization factor (0.0 to 1.0)",
    )

    @model_validator(mode="after")
    def validate_power_bounds(self) -> "PowerRequirement":
        """Ensure min_power_kw <= nominal_kw <= max_power_kw."""
        if self.min_power_kw > self.nominal_kw:
            raise ValueError(
                f"Minimum power ({self.min_power_kw} kW) cannot exceed nominal power ({self.nominal_kw} kW)"
            )
        if self.nominal_kw > self.max_power_kw:
            raise ValueError(
                f"Nominal power ({self.nominal_kw} kW) cannot exceed maximum power ({self.max_power_kw} kW)"
            )
        return self


class EnergyRequirement(BaseModel):
    """
    Cumulative electrical energy requirement (kWh).

    Calculated as:
      base_energy = nominal_kw * (duration_minutes / 60) * utilization_factor
      buffer_energy = base_energy * buffer_factor
      protected_energy = base_energy + buffer_energy
    """
    base_energy_kwh: float = Field(..., ge=0.0, description="Base calculated energy in kWh")
    buffer_kwh: float = Field(..., ge=0.0, description="Protective mission energy buffer in kWh")
    protected_energy_kwh: float = Field(..., ge=0.0, description="Total protected energy (base + buffer) in kWh")
    measured_historical_kwh: float | None = Field(
        default=None,
        ge=0.0,
        description="Actual measured consumption from past runs, if available",
    )
