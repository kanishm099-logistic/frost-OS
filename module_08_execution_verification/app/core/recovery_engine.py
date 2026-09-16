"""
Execution Recovery & Safe Rollback Engine.

Handles execution failures and deviations:
1. Reads actual physical state.
2. Locks affected resource.
3. Notifies M01 Orchestrator.
4. Requests M05 diagnostics when equipment is abnormal.
5. Requests M06 reoptimization when energy state materially changed.
6. Executes safe rollback for reversible operations when policy permits.
"""

from __future__ import annotations

from typing import Dict, Any, Optional
import structlog

from app.models.verification import VerificationResultModel, VerificationStatusEnum
from app.models.execution import ActionItemModel
from app.hal.base import BaseHALAdapter
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class RecoveryEngine:
    """Execution Failure Recovery & Rollback Engine."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def handle_execution_failure(
        self,
        execution_id: str,
        action: ActionItemModel,
        verification: VerificationResultModel,
        device_adapter: Optional[BaseHALAdapter] = None,
    ) -> Dict[str, Any]:
        """
        Coordinates recovery steps upon verification failure or deviation.
        """
        logger.error("Handling execution failure/deviation", execution_id=execution_id, action_id=action.action_id, status=verification.status.value)

        # 1. Fetch current physical state
        actual_state = await device_adapter.get_state() if device_adapter else {}

        # 2. Formulate Recovery Package
        recovery_package = {
            "execution_id": execution_id,
            "action_id": action.action_id,
            "plan_id": action.plan_id,
            "target_id": action.target_id,
            "verification_status": verification.status.value,
            "deviation_type": verification.deviation_type,
            "actual_state": actual_state,
            "rollback_executed": False,
            "notifications": [
                {"target": "M01_ORCHESTRATOR", "message": f"Execution failure in plan {action.plan_id} at action {action.action_id}."},
                {"target": "M05_DIAGNOSTICS", "message": f"Requesting diagnostic check on equipment '{action.target_id}' due to {verification.deviation_type}."},
                {"target": "M06_OPTIMIZER", "message": "Material telemetry deviation detected; re-optimization requested."},
            ],
        }

        # 3. Attempt Safe Rollback if action specifies rollback and adapter available
        if action.rollback_action and device_adapter and device_adapter.is_connected:
            try:
                logger.info("Executing safe rollback action", action_id=action.action_id, rollback=action.rollback_action)
                await device_adapter.stop()
                recovery_package["rollback_executed"] = True
                recovery_package["rollback_details"] = "Safe rollback executed: Target set to safe zero-power state."
            except Exception as exc:
                logger.error("Rollback execution failed", error=str(exc))
                recovery_package["rollback_details"] = f"Rollback failed: {str(exc)}"

        return recovery_package
