"""
Master Execution & Verification Engine.

Orchestrates the authorized execution pipeline:
Plan -> Auth Check -> Safety Check -> Action Validation -> Resource Locking -> HAL Command Execution -> Telemetry Observation -> Verification -> Recovery.
"""

from __future__ import annotations

import uuid
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import structlog

from app.models.execution import (
    ActionPlanModel,
    ExecutionStateEnum,
    ExecutionRecordModel,
)
from app.models.verification import VerificationResultModel, VerificationStatusEnum
from app.core.authorization_checker import AuthorizationChecker
from app.core.action_validator import ActionValidator
from app.core.command_manager import CommandManager
from app.core.verification_engine import VerificationEngine
from app.core.recovery_engine import RecoveryEngine
from app.core.execution_state import ExecutionStateMachine
from app.hal.device_manager import HALDeviceManager
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class ExecutionEngine:
    """Master Controlled Actuator Execution Engine."""

    def __init__(self, settings: Settings, device_manager: HALDeviceManager):
        self.settings = settings
        self.device_manager = device_manager
        self.auth_checker = AuthorizationChecker(settings)
        self.action_validator = ActionValidator(settings)
        self.command_manager = CommandManager(settings)
        self.verification_engine = VerificationEngine(settings)
        self.recovery_engine = RecoveryEngine(settings)

    async def execute_plan(
        self,
        plan: ActionPlanModel,
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute an authorized ActionPlan end-to-end.
        """
        execution_id = f"EXEC-{uuid.uuid4().hex[:8].upper()}"
        idempotency_key = idempotency_key or f"IDEMP-{plan.plan_id}-{uuid.uuid4().hex[:6]}"

        fsm = ExecutionStateMachine(execution_id)

        # 1. Idempotency Check
        if not self.command_manager.check_idempotency(idempotency_key):
            fsm.transition_to(ExecutionStateEnum.REJECTED, "Duplicate command blocked by idempotency key")
            return {
                "execution_id": execution_id,
                "plan_id": plan.plan_id,
                "status": ExecutionStateEnum.REJECTED.value,
                "reason": f"Duplicate request with idempotency_key '{idempotency_key}' already processed.",
                "verifications": [],
            }
        self.command_manager.mark_idempotency_executed(idempotency_key)

        # 2. Authorization Check (M01 Auth + M07 SAFE Status)
        fsm.transition_to(ExecutionStateEnum.AUTH_CHECK, "Verifying M01 authorization token")
        auth_valid, auth_msg = self.auth_checker.verify_plan_authorization(plan)
        if not auth_valid:
            fsm.transition_to(ExecutionStateEnum.REJECTED, auth_msg)
            return {
                "execution_id": execution_id,
                "plan_id": plan.plan_id,
                "status": ExecutionStateEnum.REJECTED.value,
                "reason": auth_msg,
                "verifications": [],
            }

        # 3. Safety Check Confirmation
        fsm.transition_to(ExecutionStateEnum.SAFETY_CHECK, "Verifying M07 safety validation clearance")
        fsm.transition_to(ExecutionStateEnum.VALIDATING, "Validating individual action parameters")

        verifications: List[VerificationResultModel] = []
        actions_completed = 0

        # Sort actions by priority (lower priority number = executed first), then by sequence
        def action_priority_key(a):
            p = a.parameters.get("priority", 10)
            if a.action_type.value in ("REDUCE_LOAD", "PAUSE_MISSION"):
                p = min(p, 1)
            return (p, a.sequence)

        sorted_actions = sorted(plan.actions, key=action_priority_key)

        for action in sorted_actions:
            target_id = action.target_id
            adapter = self.device_manager.get_adapter(target_id)
            if not adapter:
                fsm.transition_to(ExecutionStateEnum.EXECUTION_FAILED, f"Target device '{target_id}' not found in HAL registry")
                return {
                    "execution_id": execution_id,
                    "plan_id": plan.plan_id,
                    "status": ExecutionStateEnum.EXECUTION_FAILED.value,
                    "reason": f"Target device '{target_id}' not found in HAL registry.",
                    "verifications": [v.model_dump() for v in verifications],
                }

            # Local Boundary Check
            valid_act, act_msg = self.action_validator.validate_action(action, adapter)
            if not valid_act:
                fsm.transition_to(ExecutionStateEnum.REJECTED, act_msg)
                return {
                    "execution_id": execution_id,
                    "plan_id": plan.plan_id,
                    "status": ExecutionStateEnum.REJECTED.value,
                    "reason": act_msg,
                    "verifications": [v.model_dump() for v in verifications],
                }

            # Acquire Resource Lock
            lock_acquired, lock_msg = self.command_manager.acquire_resource_lock(target_id, plan.plan_id)
            if not lock_acquired:
                fsm.transition_to(ExecutionStateEnum.REJECTED, lock_msg)
                return {
                    "execution_id": execution_id,
                    "plan_id": plan.plan_id,
                    "status": ExecutionStateEnum.REJECTED.value,
                    "reason": lock_msg,
                    "verifications": [v.model_dump() for v in verifications],
                }

            try:
                # 4. Command Generation & HAL Execution
                fsm.transition_to(ExecutionStateEnum.EXECUTING, f"Executing action {action.action_type.value} on {target_id}")
                cmd = self.command_manager.translate_action_to_command(action, idempotency_key)
                attempt = await adapter.execute_command(cmd)

                if attempt.status not in ("ACKNOWLEDGED", "SENT"):
                    fsm.transition_to(ExecutionStateEnum.EXECUTION_FAILED, f"Hardware command failed: {attempt.error_message}")
                    return {
                        "execution_id": execution_id,
                        "plan_id": plan.plan_id,
                        "status": ExecutionStateEnum.EXECUTION_FAILED.value,
                        "reason": f"Hardware command failed: {attempt.error_message}",
                        "verifications": [v.model_dump() for v in verifications],
                    }

                # 5. Telemetry Observation & Verification
                fsm.transition_to(ExecutionStateEnum.OBSERVING, "Observing telemetry feedback over observation window")
                await asyncio.sleep(0.1)  # Non-blocking observation window

                fsm.transition_to(ExecutionStateEnum.VERIFYING, "Verifying actual telemetry against expected parameters")
                ver_res = await self.verification_engine.verify_action_execution(execution_id, action, adapter)
                verifications.append(ver_res)

                if ver_res.status not in (VerificationStatusEnum.SUCCESS, VerificationStatusEnum.PARTIAL_SUCCESS):
                    fsm.transition_to(ExecutionStateEnum.VERIFICATION_FAILED, ver_res.description)
                    rec_out = await self.recovery_engine.handle_execution_failure(execution_id, action, ver_res, adapter)
                    return {
                        "execution_id": execution_id,
                        "plan_id": plan.plan_id,
                        "status": ExecutionStateEnum.VERIFICATION_FAILED.value,
                        "reason": ver_res.description,
                        "verifications": [v.model_dump() for v in verifications],
                        "recovery": rec_out,
                    }

                actions_completed += 1

            finally:
                self.command_manager.release_resource_lock(target_id, plan.plan_id)

        fsm.transition_to(ExecutionStateEnum.COMPLETED, "All actions executed and verified successfully")

        return {
            "execution_id": execution_id,
            "plan_id": plan.plan_id,
            "status": ExecutionStateEnum.COMPLETED.value,
            "actions_completed": actions_completed,
            "total_actions": len(plan.actions),
            "verifications": [v.model_dump() for v in verifications],
            "state_transitions": [t.model_dump() for t in fsm.transitions],
        }
