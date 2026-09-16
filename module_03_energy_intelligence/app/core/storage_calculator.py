"""
Frost OS Module 03 — Storage Calculator.

Calculates battery available energy, temperature-adjusted charge/discharge limits,
hydrogen usable energy, and remaining storage runway under active deficit.
"""

from __future__ import annotations

from app.config.settings import Settings
from app.models.storage import BatteryState, HydrogenState


class StorageCalculator:
    """Calculates physical operational metrics for battery and hydrogen storage."""

    def __init__(
        self,
        settings: Settings | None = None,
        capacity_kwh: float | None = None,
        min_soc_pct: float | None = None,
    ) -> None:
        self.settings = settings or Settings()
        if capacity_kwh is not None:
            self.settings.battery_capacity_kwh = capacity_kwh
        if min_soc_pct is not None:
            self.settings.battery_min_soc_pct = min_soc_pct

    @staticmethod
    def calculate_temperature_derating(temp_c: float) -> float:
        """Calculate polar temperature derating factor for battery discharge."""
        if temp_c >= 15.0:
            return 1.0
        elif temp_c >= 0.0:
            return round(0.90 + (temp_c / 15.0) * 0.10, 3)
        elif temp_c >= -20.0:
            return round(0.60 + ((temp_c + 20.0) / 20.0) * 0.30, 3)
        else:
            return round(max(0.20, 0.60 + (temp_c + 20.0) * 0.02), 3)

    def calculate_usable_battery_kwh(
        self,
        soc_pct: float,
        temp_c: float = 20.0,
        soh_pct: float = 100.0,
    ) -> float:
        """Calculate usable energy strictly above minimum reserve."""
        capacity = self.settings.battery_capacity_kwh
        min_soc = self.settings.battery_min_soc_pct
        if soc_pct <= min_soc:
            return 0.0
        usable_fraction = (soc_pct - min_soc) / 100.0
        temp_factor = self.calculate_temperature_derating(temp_c)
        return round(capacity * usable_fraction * (soh_pct / 100.0) * temp_factor, 2)

    @staticmethod
    def calculate_battery_runway(
        usable_energy_kwh: float,
        net_power_kw: float,
    ) -> float | None:
        """Calculate remaining hours under deficit. If surplus, returns None."""
        if net_power_kw >= 0.0:
            return None
        deficit = abs(net_power_kw)
        if deficit <= 0.0 or usable_energy_kwh <= 0.0:
            return 0.0
        return round(usable_energy_kwh / deficit, 2)

    @staticmethod
    def calculate_hydrogen_energy_kwh(
        kg: float,
        fuel_cell_efficiency: float = 0.50,
        lhv_kwh_per_kg: float = 33.33,
    ) -> float:
        """Calculate usable electrical kWh from hydrogen mass in kg."""
        return round(kg * lhv_kwh_per_kg * fuel_cell_efficiency, 2)

    def calculate_battery_state(
        self,
        soc_pct: float,
        soh_pct: float = 100.0,
        current_power_kw: float = 0.0,
        temperature_c: float = 15.0,
        deficit_kw: float = 0.0,
    ) -> BatteryState:
        """
        Calculate usable battery energy, derated limits, and runway under deficit.
        """
        capacity = self.settings.battery_capacity_kwh
        min_soc = self.settings.battery_min_soc_pct
        max_soc = self.settings.battery_max_soc_pct
        eff_discharge = self.settings.battery_discharge_efficiency

        # 1. Usable energy above hard minimum reserve
        usable_soc_fraction = max(0.0, (soc_pct - min_soc) / 100.0)
        available_energy = capacity * usable_soc_fraction * (soh_pct / 100.0) * eff_discharge

        # 2. Temperature Derating Factors for Polar Climate
        temp_discharge_factor = self.calculate_temperature_derating(temperature_c)
        if temperature_c < -20.0:
            temp_charge_factor = 0.15
        elif temperature_c < 0.0:
            temp_charge_factor = 0.50
        elif temperature_c > 45.0:
            temp_charge_factor = 0.50
            temp_discharge_factor = 0.70
        else:
            temp_charge_factor = 1.0

        # 3. SOC Boundary Tapering
        soc_charge_factor = 1.0
        soc_discharge_factor = 1.0

        if soc_pct >= max_soc:
            soc_charge_factor = 0.0
        elif soc_pct > 85.0:
            soc_charge_factor = max(0.0, (max_soc - soc_pct) / 15.0)

        if soc_pct <= min_soc:
            soc_discharge_factor = 0.0
        elif soc_pct < (min_soc + 10.0):
            soc_discharge_factor = max(0.0, (soc_pct - min_soc) / 10.0)

        # Apply limits
        charge_limit = self.settings.battery_max_charge_kw * temp_charge_factor * soc_charge_factor
        discharge_limit = self.settings.battery_max_discharge_kw * temp_discharge_factor * soc_discharge_factor

        # 4. Runway calculation under active deficit
        runway_hours = None
        effective_deficit = deficit_kw if deficit_kw > 0.0 else (current_power_kw if current_power_kw > 0.0 else 0.0)
        if effective_deficit > 0.0 and available_energy > 0.0:
            runway_hours = round(available_energy / effective_deficit, 2)

        return BatteryState(
            soc_pct=round(soc_pct, 2),
            soh_pct=round(soh_pct, 2),
            capacity_kwh=capacity,
            available_energy_kwh=round(available_energy, 2),
            current_power_kw=round(current_power_kw, 2),
            charge_limit_kw=round(charge_limit, 2),
            discharge_limit_kw=round(discharge_limit, 2),
            temperature_c=round(temperature_c, 1),
            estimated_runway_hours=runway_hours,
        )

    def calculate_hydrogen_state(
        self,
        level_pct: float,
        fuel_cell_power_kw: float = 0.0,
        electrolyzer_power_kw: float = 0.0,
        pressure_bar: float = 350.0,
    ) -> HydrogenState:
        """
        Calculate usable electrical energy from stored hydrogen chemical reserve.
        """
        capacity = self.settings.hydrogen_capacity_kwh
        min_reserve = self.settings.hydrogen_min_reserve_pct
        eff_fc = self.settings.hydrogen_fuel_cell_efficiency

        usable_fraction = max(0.0, (level_pct - min_reserve) / 100.0)
        usable_kwh = capacity * usable_fraction * eff_fc
        max_discharge = self.settings.hydrogen_max_fuel_cell_kw if level_pct > min_reserve else 0.0

        return HydrogenState(
            level_pct=round(level_pct, 2),
            capacity_kwh=capacity,
            usable_energy_kwh=round(usable_kwh, 2),
            fuel_cell_power_kw=round(fuel_cell_power_kw, 2),
            electrolyzer_power_kw=round(electrolyzer_power_kw, 2),
            max_discharge_kw=round(max_discharge, 2),
            pressure_bar=round(pressure_bar, 1),
        )
