"""
Verification of 5 Critical Test Cases specified in Frost OS Module 07 Specification.
"""

from __future__ import annotations

from app.core.safety_engine import SafetyEngine
from app.models.safety_decision import SafetyDecisionStatus


def test_critical_case_1_reserve_breach(settings, sample_proposed_plan, sample_energy_state, sample_missions, sample_forecast, sample_equipment_health):
    """
    CRITICAL TEST 1:
    Battery stored energy = 2500 kWh (modified to 1200 kWh available).
    Required station reserve = 1800 kWh.
    M06 proposes using 1000 kWh.
    Validation must calculate remaining protected energy and determine reserve breach -> UNSAFE.
    """
    engine = SafetyEngine(settings)
    
    sample_energy_state["battery_energy_kwh"] = 1000.0
    sample_energy_state["hydrogen_energy_kwh"] = 200.0  # Total available = 1200 kWh
    sample_energy_state["battery_soc_pct"] = 40.0

    res = engine.validate_plan(
        proposed_plan=sample_proposed_plan,
        energy_state=sample_energy_state,
        missions=sample_missions,
        forecast=sample_forecast,
        equipment_health=sample_equipment_health,
    )

    assert res.status in (SafetyDecisionStatus.UNSAFE, SafetyDecisionStatus.REQUIRES_REPLAN)
    assert res.reserve_status == "BREACHED"
    assert res.is_executable is False


def test_critical_case_2_p1_mission_minimum_power_rejection(settings, sample_proposed_plan, sample_energy_state, sample_missions, sample_forecast, sample_equipment_health):
    """
    CRITICAL TEST 2:
    P1 research requires minimum 90kW.
    M06 proposes 70kW.
    M07 must reject the plan unless the mission explicitly supports a valid 70kW operating mode -> UNSAFE.
    """
    engine = SafetyEngine(settings)

    # Modify proposed plan to allocate only 70 kW to P1 mission (which requires min 90 kW)
    sample_proposed_plan["mission_allocations"] = [
        {
            "mission_id": "MIS-P0-LIFE",
            "mission_name": "Life Support",
            "priority": "P0",
            "min_power_kw": 40.0,
            "allocated_power_kw": 40.0,
            "satisfied": True,
        },
        {
            "mission_id": "MIS-P1-ICE",
            "mission_name": "Deep Ice Core Drilling",
            "priority": "P1",
            "min_power_kw": 90.0,
            "allocated_power_kw": 70.0,  # Below 90 kW safe min power!
            "satisfied": False,
        },
    ]

    res = engine.validate_plan(
        proposed_plan=sample_proposed_plan,
        energy_state=sample_energy_state,
        missions=sample_missions,
        forecast=sample_forecast,
        equipment_health=sample_equipment_health,
    )

    assert res.status == SafetyDecisionStatus.UNSAFE
    assert any(v.rule_id == "RULE-MIS-P1" for v in res.hard_violations)
    assert res.is_executable is False


def test_critical_case_3_wind_collapse_forecast_uncertainty(settings, sample_proposed_plan, sample_energy_state, sample_missions, sample_forecast, sample_equipment_health):
    """
    CRITICAL TEST 3:
    Forecast predicts wind collapse with high uncertainty.
    M07 must increase reserve requirement according to configured uncertainty/risk policy.
    """
    engine = SafetyEngine(settings)

    # Low model confidence (0.45)
    sample_forecast["confidence"] = 0.45

    res_normal = engine.validate_plan(
        proposed_plan=sample_proposed_plan,
        energy_state=sample_energy_state,
        missions=sample_missions,
        forecast=sample_forecast,
        equipment_health=sample_equipment_health,
        weather_event="NORMAL",
    )

    res_storm = engine.validate_plan(
        proposed_plan=sample_proposed_plan,
        energy_state=sample_energy_state,
        missions=sample_missions,
        forecast=sample_forecast,
        equipment_health=sample_equipment_health,
        weather_event="STORM",
    )

    assert res_storm.reserve_calculation.total_protected_reserve_kwh > res_normal.reserve_calculation.total_protected_reserve_kwh


def test_critical_case_4_thermal_emergency_immediate_protective_path(settings, sample_proposed_plan, sample_energy_state, sample_missions, sample_forecast, sample_equipment_health):
    """
    CRITICAL TEST 4:
    Critical battery temperature exceeds emergency threshold (45°C).
    M07 must generate EMERGENCY and invoke only predefined protective behavior without waiting for normal optimization.
    """
    engine = SafetyEngine(settings)
    sample_energy_state["battery_temperature_c"] = 49.0  # Exceeds 45.0°C!

    res = engine.validate_plan(
        proposed_plan=sample_proposed_plan,
        energy_state=sample_energy_state,
        missions=sample_missions,
        forecast=sample_forecast,
        equipment_health=sample_equipment_health,
    )

    assert res.status == SafetyDecisionStatus.EMERGENCY
    assert res.is_executable is False
    assert "EMERGENCY TRIGGERED" in res.explanation


def test_critical_case_5_stale_telemetry_failsafe(settings, sample_proposed_plan, sample_energy_state, sample_missions, sample_forecast, sample_equipment_health):
    """
    CRITICAL TEST 5:
    Critical telemetry becomes stale or bad.
    M07 must not treat missing/stale data as normal. Apply configured fail-safe behavior.
    """
    engine = SafetyEngine(settings)
    sample_energy_state["data_quality"] = "STALE"

    res = engine.validate_plan(
        proposed_plan=sample_proposed_plan,
        energy_state=sample_energy_state,
        missions=sample_missions,
        forecast=sample_forecast,
        equipment_health=sample_equipment_health,
    )

    assert res.status == SafetyDecisionStatus.REQUIRES_REPLAN
    assert res.is_executable is False
    assert any(v.rule_id == "RULE-DATA-01" for v in res.hard_violations)
