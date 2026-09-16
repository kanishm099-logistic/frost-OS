"""
Frost OS Module 03 — Storage & Polar Derating Tests.
"""

from __future__ import annotations

import pytest

from app.core.storage_calculator import StorageCalculator


def test_battery_temperature_derating_curve():
    """Verify Antarctic sub-zero temperature derating factors."""
    calc = StorageCalculator()

    # Optimal indoor room temp (20°C)
    derate_warm = calc.calculate_temperature_derating(20.0)
    assert derate_warm == 1.0

    # Mild polar container temp (-5°C)
    derate_cold = calc.calculate_temperature_derating(-5.0)
    assert 0.80 <= derate_cold < 1.0

    # Extreme sub-zero unheated container (-25°C)
    derate_extreme = calc.calculate_temperature_derating(-25.0)
    assert derate_extreme <= 0.50


def test_battery_usable_energy_above_reserve():
    """Verify usable energy calculation enforces 20% minimum safety reserve."""
    calc = StorageCalculator(capacity_kwh=600.0, min_soc_pct=20.0)

    # At 72% SOC with 1.0 derating factor:
    # Usable energy = 600 * (72 - 20)/100 = 600 * 0.52 = 312.0 kWh
    usable = calc.calculate_usable_battery_kwh(soc_pct=72.0, temp_c=20.0)
    assert usable == 312.0

    # At or below 20% SOC:
    # Usable energy must be 0.0 kWh (reserved for station survival)
    usable_low = calc.calculate_usable_battery_kwh(soc_pct=20.0, temp_c=20.0)
    assert usable_low == 0.0

    usable_sub = calc.calculate_usable_battery_kwh(soc_pct=15.0, temp_c=20.0)
    assert usable_sub == 0.0


def test_battery_runway_under_deficit():
    """Verify runway calculation under real deficit."""
    calc = StorageCalculator(capacity_kwh=600.0, min_soc_pct=20.0)

    # 312 kWh usable energy under 40 kW deficit -> 7.8 hours runway
    runway_hours = calc.calculate_battery_runway(usable_energy_kwh=312.0, net_power_kw=-40.0)
    assert runway_hours == 7.8

    # Under surplus (+50 kW net), runway is None (system is not draining battery)
    runway_surplus = calc.calculate_battery_runway(usable_energy_kwh=312.0, net_power_kw=50.0)
    assert runway_surplus is None


def test_hydrogen_usable_electrical_energy():
    """Verify chemical to electrical conversion using LHV and Fuel Cell efficiency."""
    calc = StorageCalculator()

    # 100 kg H2 with 50% fuel cell efficiency and 33.33 kWh/kg LHV
    # Electrical energy = 100 * 33.33 * 0.50 = 1666.5 kWh
    usable_h2 = calc.calculate_hydrogen_energy_kwh(kg=100.0, fuel_cell_efficiency=0.50)
    assert round(usable_h2, 1) == 1666.5
