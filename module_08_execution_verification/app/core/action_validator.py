"""
Local Action Boundary & Device Limits Validator.

Verifies high-level actions against device capability registered boundaries
BEFORE hardware interaction.
"""

from __future__ import annotations

from typing import Dict, Any, Tuple
import structlog

from app.models.execution import ActionItemModel, ActionTypeEnum
from app.hal.base import BaseHALAdapter
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class ActionValidator:
    """Validates action parameters against physical device boundaries."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def validate_action(
        self,
        action: ActionItemModel,
        device_adapter: BaseHALAdapter,
    ) -> Tuple[bool, str]:
        """
        Validates action against target device capabilities.
        Returns (is_valid, error_description).
        """
        # 1. Device Availability & Link Check
        if not device_adapter.is_connected:
            return False, f"Action REJECTED: Target device '{action.target_id}' is offline or disconnected."

        caps = device_adapter.capabilities
        supported_actions = caps.get("supported_actions", [])

        # 2. Supported Action Check
        if action.action_type.value not in supported_actions and not caps.get("allow_all_actions", True):
            return False, f"Action REJECTED: Target device '{action.target_id}' does not support action '{action.action_type.value}'."

        # 3. Power Limits Check
        req_power = float(action.parameters.get("power_kw", action.parameters.get("discharge_rate_kw", action.parameters.get("charge_rate_kw", 0.0))))
        max_power = float(caps.get("max_power_kw", 250.0))

        if req_power > max_power + 0.01:
            logger.warning("Local action validation failed: Requested power exceeds max device limit", requested=req_power, max_limit=max_power)
            return False, f"Action REJECTED: Requested power ({req_power} kW) exceeds device '{action.target_id}' registered max capacity ({max_power} kW)."

        # 4. SOC Limits Check (for Battery actions)
        if action.action_type in (ActionTypeEnum.CHARGE_BATTERY, ActionTypeEnum.DISCHARGE_BATTERY):
            curr_soc = float(caps.get("current_soc_pct", 50.0))
            min_soc = float(caps.get("min_soc_pct", 20.0))
            max_soc = float(caps.get("max_soc_pct", 95.0))

            if action.action_type == ActionTypeEnum.DISCHARGE_BATTERY and curr_soc <= min_soc:
                return False, f"Action REJECTED: Battery '{action.target_id}' SOC ({curr_soc}%) is at or below minimum threshold ({min_soc}%)."

            if action.action_type == ActionTypeEnum.CHARGE_BATTERY and curr_soc >= max_soc:
                return False, f"Action REJECTED: Battery '{action.target_id}' SOC ({curr_soc}%) is at maximum capacity ({max_soc}%)."

        return True, "Action local boundary validation passed."
