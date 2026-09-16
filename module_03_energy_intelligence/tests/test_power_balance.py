"""
Frost OS Module 03 — Power Balance & Numerical Integration Tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from app.core.load_analyzer import LoadAnalyzer
from app.core.power_calculator import PowerCalculator
from app.models.energy_state import GenerationBreakdown, LoadBreakdown
from app.models.telemetry import QualityStatus


def test_net_power_balance_benchmark_deficit():
    """Verify Antarctic benchmark: 120 kW solar + 180 kW wind - 340 kW load = -40 kW deficit."""
    calc = PowerCalculator()
    gen = GenerationBreakdown.from_inputs(
        solar_kw=120.0,
        wind_kw=180.0,
        total_generation_kw=300.0,
    )
    load = LoadBreakdown.from_inputs(
        total_load_kw=340.0,
        critical_kw=120.0,
        operational_kw=100.0,
        flexible_kw=70.0,
        deferrable_kw=50.0,
    )
    net_kw = calc.calculate_net_power(gen.total_generation_kw, load.total_load_kw)
    assert net_kw == -40.0


def test_net_power_balance_surplus():
    """Verify surplus when renewable generation exceeds station load."""
    calc = PowerCalculator()
    gen_kw = 450.0
    load_kw = 340.0
    net_kw = calc.calculate_net_power(gen_kw, load_kw)
    assert net_kw == 110.0


def test_generation_breakdown_calculator():
    """Test aggregation of multiple generation sources into GenerationBreakdown."""
    calc = PowerCalculator()
    sources = [
        {"type": "solar", "power_kw": 80.0},
        {"type": "solar", "power_kw": 40.0},
        {"type": "wind", "power_kw": 180.0},
        {"type": "generator", "power_kw": 0.0},
    ]
    gen = calc.build_generation_breakdown(sources)
    assert gen.solar_kw == 120.0
    assert gen.wind_kw == 180.0
    assert gen.total_generation_kw == 300.0
    assert gen.solar_pct == 40.0
    assert gen.wind_pct == 60.0


def test_load_analyzer_priority_grouping():
    """Verify LoadAnalyzer groups telemetry into P0-P4 categories correctly."""
    analyzer = LoadAnalyzer()
    load_telemetry = [
        {"device_id": "life_support", "power_kw": 120.0, "priority": "P0"},
        {"device_id": "radome_comms", "power_kw": 20.0, "priority": "P1"},
        {"device_id": "science_lab", "power_kw": 100.0, "priority": "P2"},
        {"device_id": "water_heater", "power_kw": 50.0, "priority": "P3"},
        {"device_id": "snow_melter", "power_kw": 50.0, "priority": "P4"},
    ]
    breakdown = analyzer.analyze_loads(load_telemetry)
    assert breakdown.critical_kw == 140.0  # P0 + P1
    assert breakdown.operational_kw == 100.0  # P2
    assert breakdown.flexible_kw == 50.0  # P3
    assert breakdown.deferrable_kw == 50.0  # P4
    assert breakdown.total_load_kw == 340.0


def test_irregular_numerical_energy_integration():
    """Verify numerical trapezoidal/piecewise energy integration for non-uniform intervals."""
    calc = PowerCalculator()
    t0 = datetime(2026, 9, 16, 12, 0, 0, tzinfo=timezone.utc)

    # Power profile over irregular intervals
    # t0: 100 kW
    # t0 + 15 min (900s): 120 kW
    # t0 + 45 min (2700s): 80 kW
    # t0 + 60 min (3600s): 100 kW
    timestamps = [
        t0,
        t0 + timedelta(minutes=15),
        t0 + timedelta(minutes=45),
        t0 + timedelta(minutes=60),
    ]
    powers = [100.0, 120.0, 80.0, 100.0]

    energy_kwh = calc.integrate_energy_kwh(powers, timestamps)
    # Average power roughly 100 kW over 1 hour = ~100 kWh
    assert 95.0 <= energy_kwh <= 105.0
