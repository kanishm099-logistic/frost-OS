"""
Frost OS Module 03 — Storage Subsystem Models.

Strongly typed state models for Battery Energy Storage System (BESS),
Hydrogen Storage & Fuel Cell/Electrolyzer, and Thermal Storage.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BatteryState(BaseModel):
    """
    Real-time operational state of the Battery Energy Storage System.

    Sign convention:
      current_power_kw > 0 : Discharging (supplying power to microgrid)
      current_power_kw < 0 : Charging (absorbing power from microgrid)
    """
    soc_pct: float = Field(default=50.0, ge=0.0, le=100.0, description="State of Charge (%)")
    soh_pct: float = Field(default=100.0, ge=0.0, le=100.0, description="State of Health (%)")
    capacity_kwh: float = Field(default=6000.0, ge=0.0, description="Nameplate total energy capacity in kWh")
    available_energy_kwh: float = Field(default=3000.0, ge=0.0, description="Usable energy above minimum reserve in kWh")
    current_power_kw: float = Field(default=0.0, description="Instantaneous power draw/charge in kW (+ discharge, - charge)")
    charge_limit_kw: float = Field(default=300.0, ge=0.0, description="Safe maximum charging power limit in kW")
    discharge_limit_kw: float = Field(default=350.0, ge=0.0, description="Safe maximum discharging power limit in kW")
    temperature_c: float = Field(default=15.0, description="Core battery pack temperature in °C")
    estimated_runway_hours: float | None = Field(
        default=None,
        ge=0.0,
        description="Hours until minimum SOC threshold under current net deficit",
    )

    @property
    def usable_energy_kwh(self) -> float:
        return self.available_energy_kwh

    @property
    def runway_hours(self) -> float | None:
        return self.estimated_runway_hours

    @property
    def power_kw(self) -> float:
        return self.current_power_kw


class HydrogenState(BaseModel):
    """
    Real-time operational state of Hydrogen storage and fuel cell / electrolyzer.

    Separates stored chemical energy from instantaneous electrical conversion power.
    """
    level_pct: float = Field(default=80.0, ge=0.0, le=100.0, description="Hydrogen storage tank level (%)")
    capacity_kwh: float = Field(default=10000.0, ge=0.0, description="Total chemical energy capacity in kWh")
    usable_energy_kwh: float = Field(default=6000.0, ge=0.0, description="Deliverable electrical energy after conversion in kWh")
    fuel_cell_power_kw: float = Field(default=0.0, ge=0.0, description="Fuel cell electrical generation in kW")
    electrolyzer_power_kw: float = Field(default=0.0, ge=0.0, description="Electrolyzer power consumption in kW")
    max_discharge_kw: float = Field(default=200.0, ge=0.0, description="Max fuel cell output capacity in kW")
    pressure_bar: float = Field(default=350.0, ge=0.0, description="Storage vessel pressure in bar")

    @property
    def current_level_kg(self) -> float:
        return round((self.level_pct / 100.0) * 200.0, 1)

    @property
    def capacity_kg(self) -> float:
        return 200.0


class ThermalStorageState(BaseModel):
    """Operational state of station thermal buffer/hot water loops."""
    stored_kwh: float = Field(default=500.0, ge=0.0, description="Stored thermal energy in kWh equivalent")
    temperature_c: float = Field(default=65.0, description="Thermal buffer core temperature in °C")
    power_kw: float = Field(default=0.0, description="Thermal power draw / injection in kW")
