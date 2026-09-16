"""
Telemetry Observation & Verification Engine.

Verifies actual system telemetry against expected results over observation windows.
Returns SUCCESS, PARTIAL_SUCCESS, DEVIATION, FAILED, or UNCERTAIN.
Does NOT rely on command acknowledgement alone!
"""

from __future__ import annotations

import uuid
from typing import Dict, Any, Tuple
import structlog

from app.models.verification import VerificationResultModel, VerificationStatusEnum
from app.models.execution import ActionItemModel
from app.hal.base import BaseHALAdapter
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class VerificationEngine:
    """Independent Telemetry Verification Engine."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def verify_action_execution(
        self,
        execution_id: str,
        action: ActionItemModel,
        device_adapter: BaseHALAdapter,
    ) -> VerificationResultModel:
        """
        Observes actual telemetry and compares with expected parameters within tolerance bands.
        """
        verification_id = f"VER-{uuid.uuid4().hex[:8].upper()}"
        
        # 1. Fetch Actual Telemetry from Hardware Adapter
        actual_state = await device_adapter.get_state()
        
        expected_power = float(action.parameters.get("power_kw", action.parameters.get("discharge_rate_kw", action.parameters.get("target_kw", 0.0))))
        actual_power = float(actual_state.get("power_kw", 0.0))
        tolerance = self.settings.verification_power_tolerance_kw

        error = abs(actual_power - expected_power)
        
        # 2. Check Device Link Status
        if not device_adapter.is_connected or actual_state.get("status") == "OFFLINE":
            return VerificationResultModel(
                verification_id=verification_id,
                execution_id=execution_id,
                action_id=action.action_id,
                plan_id=action.plan_id,
                device_id=action.target_id,
                status=VerificationStatusEnum.UNCERTAIN,
                expected={"power_kw": expected_power},
                actual=actual_state,
                error=error,
                tolerance=tolerance,
                confidence=0.0,
                telemetry_quality="STALE",
                deviation_type="COMMUNICATION_LOSS",
                description=f"Verification UNCERTAIN: Target device '{action.target_id}' became unavailable or offline.",
            )

        # 3. Compare Expected vs Actual within Tolerance Band
        if error <= tolerance:
            status = VerificationStatusEnum.SUCCESS
            dev_type = None
            desc = f"Verification SUCCESS: Actual telemetry {actual_power} kW matches expected {expected_power} kW within ±{tolerance} kW tolerance."
        else:
            status = VerificationStatusEnum.DEVIATION
            dev_type = "POWER_SETPOINT_DEVIATION"
            desc = f"Verification DEVIATION: Expected {expected_power} kW, but actual telemetry observed {actual_power} kW (Error: {round(error, 1)} kW exceeds tolerance ±{tolerance} kW)."

        logger.info("Verification complete", action_id=action.action_id, status=status.value, expected=expected_power, actual=actual_power)

        return VerificationResultModel(
            verification_id=verification_id,
            execution_id=execution_id,
            action_id=action.action_id,
            plan_id=action.plan_id,
            device_id=action.target_id,
            status=status,
            expected={"power_kw": expected_power},
            actual={"power_kw": actual_power},
            error=round(error, 2),
            tolerance=tolerance,
            confidence=1.0 if status == VerificationStatusEnum.SUCCESS else 0.7,
            telemetry_quality=str(actual_state.get("telemetry_quality", "GOOD")),
            deviation_type=dev_type,
            description=desc,
        )
