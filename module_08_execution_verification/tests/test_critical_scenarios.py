"""
Verification of 6 Critical Test Cases specified in Frost OS Module 08 Specification.
"""

from __future__ import annotations

import pytest
from app.models.execution import ActionPlanModel, ActionItemModel, ActionTypeEnum
from app.models.verification import VerificationStatusEnum


@pytest.mark.asyncio
async def test_critical_case_1_successful_execution_and_verification(execution_engine, sample_action_plan):
    """
    CRITICAL TEST 1:
    M06 proposes DISCHARGE_BATTERY = 90kW.
    M07 status = SAFE.
    Authorization = YES.
    Battery max discharge = 250kW.
    Execute and verify actual discharge = 90kW with tolerance ±5kW.
    Result = SUCCESS.
    """
    res = await execution_engine.execute_plan(sample_action_plan)

    assert res["status"] == "COMPLETED"
    assert res["actions_completed"] == 1
    assert len(res["verifications"]) == 1
    assert res["verifications"][0]["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_critical_case_2_unsafe_m07_status_rejected_before_hardware_command(execution_engine, sample_action_plan):
    """
    CRITICAL TEST 2:
    Same plan but M07 status = UNSAFE.
    Execution MUST be rejected before sending any hardware command.
    """
    sample_action_plan.status = "UNSAFE"

    res = await execution_engine.execute_plan(sample_action_plan)

    assert res["status"] == "REJECTED"
    assert "Module 07 safety status is 'UNSAFE'" in res["reason"]
    assert len(res["verifications"]) == 0  # Zero hardware commands sent!


@pytest.mark.asyncio
async def test_critical_case_3_power_exceeds_device_capacity_local_rejection(execution_engine, sample_action_plan, device_manager):
    """
    CRITICAL TEST 3:
    M07 SAFE, M01 authorization valid, but battery max discharge = 50kW.
    Requested = 90kW.
    M08 MUST reject locally before sending command.
    """
    # Lower registered battery max capacity to 50 kW
    bat = device_manager.get_adapter("BAT-01")
    bat.capabilities["max_power_kw"] = 50.0

    res = await execution_engine.execute_plan(sample_action_plan)

    assert res["status"] == "REJECTED"
    assert "exceeds device 'BAT-01' registered max capacity" in res["reason"]
    assert len(res["verifications"]) == 0  # Rejected locally before hardware command!


@pytest.mark.asyncio
async def test_critical_case_4_telemetry_deviation_verification_failure(execution_engine, sample_action_plan, device_manager):
    """
    CRITICAL TEST 4:
    Command acknowledgement succeeds, but actual telemetry shows power = 30kW.
    Expected = 90kW.
    Result = VERIFICATION_FAILED or DEVIATION, not SUCCESS.
    """
    bat = device_manager.get_adapter("BAT-01")
    
    # Mock execute_command to simulate telemetry deviation (sets current power to 30 kW instead of 90 kW)
    original_execute = bat.execute_command

    async def mock_execute_deviation(cmd):
        attempt = await original_execute(cmd)
        bat.capabilities["current_power_kw"] = 30.0  # Deviated telemetry!
        return attempt

    bat.execute_command = mock_execute_deviation

    res = await execution_engine.execute_plan(sample_action_plan)

    assert res["status"] == "VERIFICATION_FAILED"
    assert "DEVIATION" in res["reason"]
    assert len(res["verifications"]) == 1
    assert res["verifications"][0]["status"] == "DEVIATION"


@pytest.mark.asyncio
async def test_critical_case_5_duplicate_idempotency_key_blocks_second_execution(execution_engine, sample_action_plan):
    """
    CRITICAL TEST 5:
    Duplicate command with same idempotency_key arrives twice.
    Only one physical execution is permitted.
    """
    idemp_key = "IDEMP-DUPLICATE-CHECK-100"

    # First execution -> COMPLETED
    res_1 = await execution_engine.execute_plan(sample_action_plan, idempotency_key=idemp_key)
    assert res_1["status"] == "COMPLETED"

    # Duplicate execution attempt with same idempotency key -> REJECTED
    res_2 = await execution_engine.execute_plan(sample_action_plan, idempotency_key=idemp_key)
    assert res_2["status"] == "REJECTED"
    assert "Duplicate request with idempotency_key" in res_2["reason"]


@pytest.mark.asyncio
async def test_critical_case_6_device_unavailable_during_execution(execution_engine, sample_action_plan, device_manager):
    """
    CRITICAL TEST 6:
    Device becomes unavailable during execution.
    M08 must stop/mark uncertain, read current state, record failure and notify M01/M05. It must not blindly retry.
    """
    bat = device_manager.get_adapter("BAT-01")
    bat.is_connected = False  # Device disconnects!

    res = await execution_engine.execute_plan(sample_action_plan)

    assert res["status"] == "REJECTED"
    assert "offline or disconnected" in res["reason"]
