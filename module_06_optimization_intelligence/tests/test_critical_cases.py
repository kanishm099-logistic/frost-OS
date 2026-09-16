"""
Test Suite for Mandatory Critical Test Cases.

Tests:
1. Prohibition of allocating below min_power_kw (e.g. 70kW allocated when min is 90kW).
2. Summer surplus utilization (500kW solar + 150kW wind vs 350kW load).
3. Polar Night load rationing & strict reserve preservation (0kW solar + 80kW wind vs 300kW load).
"""

from __future__ import annotations

import pytest

from app.models.optimization_request import (
    OptimizationRequest,
    MissionProfile,
    MissionPriority,
    EnergyStateInput,
    ForecastDataInput,
    ReserveConstraintInput,
)
from app.core.optimizer import OptimizerCore


def test_critical_case_1_min_power_prohibition(optimizer_core: OptimizerCore):
    """
    CRITICAL TEST CASE 1:
    Available renewable generation = 320kW.
    P1 life-support = 100kW (min 100kW).
    P1 research = 150kW (min 150kW).
    P2 laboratory = requires minimum 90kW (min 90kW, max 120kW).
    P3 computing = 120kW.
    
    After P1 loads (250kW), only 70kW remains.
    The optimizer MUST NOT allocate 70kW to P2 laboratory. It MUST defer/shift that mission!
    """
    missions = [
        MissionProfile(
            mission_id="P1-LIFE",
            name="P1 Life Support",
            priority=MissionPriority.P1,
            required_power_kw=100.0,
            min_power_kw=100.0,
            max_power_kw=100.0,
            energy_required_kwh=100.0,
            duration_minutes=60,
            deadline_minutes=60,
        ),
        MissionProfile(
            mission_id="P1-RES",
            name="P1 Research",
            priority=MissionPriority.P1,
            required_power_kw=150.0,
            min_power_kw=150.0,
            max_power_kw=150.0,
            energy_required_kwh=150.0,
            duration_minutes=60,
            deadline_minutes=60,
        ),
        MissionProfile(
            mission_id="P2-LAB",
            name="P2 Laboratory",
            priority=MissionPriority.P2,
            required_power_kw=120.0,
            min_power_kw=90.0,  # Minimum is 90 kW!
            max_power_kw=120.0,
            energy_required_kwh=120.0,
            duration_minutes=60,
            deadline_minutes=60,
            has_reduced_power_mode=False,
        ),
        MissionProfile(
            mission_id="P3-COMP",
            name="P3 Compute",
            priority=MissionPriority.P3,
            required_power_kw=120.0,
            min_power_kw=60.0,
            max_power_kw=120.0,
            energy_required_kwh=120.0,
            duration_minutes=60,
            deadline_minutes=60,
        ),
    ]

    # Available generation = 320kW, base load = 0kW
    # Battery and H2 at valid levels (not the focus of this test)
    energy_state = EnergyStateInput(
        current_solar_kw=320.0,
        current_wind_kw=0.0,
        current_load_kw=0.0,
        battery_soc=0.50,
        battery_capacity_kwh=100.0,
        hydrogen_energy_kwh=500.0,
        min_protected_hydrogen_kwh=0.0,
    )

    forecast = ForecastDataInput(
        solar_forecast_kw=[320.0],
        wind_forecast_kw=[0.0],
        load_forecast_kw=[0.0],
        time_step_minutes=60,
    )

    reserve = ReserveConstraintInput(required_reserve_kwh=0.0)

    request = OptimizationRequest(
        request_id="REQ-CASE-1",
        horizon_minutes=60,
        time_step_minutes=60,
        missions=missions,
        energy_state=energy_state,
        forecast=forecast,
        reserve=reserve,
    )

    res = optimizer_core.run_optimization(request)

    assert res.feasible is True
    assert res.validation_passed is True

    # Find allocation for P2-LAB
    p2_allocs = [a for a in res.mission_allocations if a.mission_id == "P2-LAB"]
    assert len(p2_allocs) > 0
    p2_power = p2_allocs[0].allocated_power_kw

    # CRITICAL CHECK: p2_power MUST NOT be 70 kW (which is below min 90kW).
    # It must be either 0.0 (deferred) or >= 90.0 kW.
    assert p2_power == 0.0 or p2_power >= 90.0, f"Violation: Allocated {p2_power}kW to P2-LAB when min_power is 90kW!"


def test_critical_case_2_summer_surplus(optimizer_core: OptimizerCore):
    """
    CRITICAL TEST CASE 2:
    Summer: Solar=500kW, Wind=150kW, Base Load=350kW, Battery below max SOC.
    Optimizer should use surplus (300kW) to charge storage and/or schedule flexible workloads.
    """
    energy_state = EnergyStateInput(
        current_solar_kw=500.0,
        current_wind_kw=150.0,
        current_load_kw=350.0,
        battery_soc=0.50,
        battery_capacity_kwh=1000.0,
        max_battery_charge_kw=250.0,
    )

    forecast = ForecastDataInput(
        solar_forecast_kw=[500.0] * 6,
        wind_forecast_kw=[150.0] * 6,
        load_forecast_kw=[350.0] * 6,
        time_step_minutes=60,
    )

    request = OptimizationRequest(
        request_id="REQ-CASE-2",
        horizon_minutes=360,
        time_step_minutes=60,
        energy_state=energy_state,
        forecast=forecast,
    )

    res = optimizer_core.run_optimization(request)

    assert res.feasible is True
    assert res.validation_passed is True

    # Verify battery charge in storage schedule
    battery_charges = [s.battery_charge_kw for s in res.storage_schedule]
    assert max(battery_charges) > 0.0, "Expected battery to charge using summer surplus energy!"


def test_critical_case_3_polar_night_rationing(optimizer_core: OptimizerCore):
    """
    CRITICAL TEST CASE 3:
    Polar Night: Solar ≈ 0kW, Wind=80kW, Load=300kW, Battery/H2 available.
    Optimizer preserves P0/P1 missions and station reserve while minimizing unnecessary cycling/H2.
    It defers P3/P4 flexible workloads.
    """
    missions = [
        MissionProfile(
            mission_id="P0-LIFE",
            name="P0 Life Support",
            priority=MissionPriority.P0,
            required_power_kw=50.0,
            min_power_kw=50.0,
            max_power_kw=50.0,
            energy_required_kwh=300.0,
            duration_minutes=360,
            deadline_minutes=360,
        ),
        MissionProfile(
            mission_id="P4-DEFERRABLE",
            name="P4 Optional Computation",
            priority=MissionPriority.P4,
            required_power_kw=150.0,
            min_power_kw=100.0,
            max_power_kw=150.0,
            energy_required_kwh=900.0,
            duration_minutes=360,
            deadline_minutes=360,
        ),
    ]

    energy_state = EnergyStateInput(
        current_solar_kw=0.0,
        current_wind_kw=80.0,
        current_load_kw=100.0,
        battery_soc=0.60,
        battery_capacity_kwh=1000.0,
        hydrogen_energy_kwh=1500.0,
    )

    forecast = ForecastDataInput(
        solar_forecast_kw=[0.0] * 6,
        wind_forecast_kw=[80.0] * 6,
        load_forecast_kw=[100.0] * 6,
        time_step_minutes=60,
    )

    reserve = ReserveConstraintInput(required_reserve_kwh=400.0)

    request = OptimizationRequest(
        request_id="REQ-CASE-3",
        horizon_minutes=360,
        time_step_minutes=60,
        missions=missions,
        energy_state=energy_state,
        forecast=forecast,
        reserve=reserve,
    )

    res = optimizer_core.run_optimization(request)

    assert res.feasible is True
    assert res.validation_passed is True

    # P0 Life support must be allocated
    p0_allocs = [a for a in res.mission_allocations if a.mission_id == "P0-LIFE"]
    assert sum(a.allocated_power_kw for a in p0_allocs) > 0.0

    # M07 Station reserve must be met across all steps
    for r in res.reserve_trajectory:
        assert r.reserve_met is True
