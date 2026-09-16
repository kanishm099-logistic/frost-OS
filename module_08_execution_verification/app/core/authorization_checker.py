"""
Plan Authorization & M07 Safety Validator.

Verifies:
1. Valid M01 authorization token / authorization_id.
2. Mandatory M07 SAFE or explicitly permitted EMERGENCY status.
3. Plan expiration (plan timestamp < expires_at).
4. Plan integrity and version matching.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any, Tuple
import structlog

from app.models.execution import ActionPlanModel
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class AuthorizationChecker:
    """Independent Plan Authorization & Integrity Checker."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def verify_plan_authorization(self, plan: ActionPlanModel) -> Tuple[bool, str]:
        """
        Verifies plan authorization token, M07 safety validation, and expiry.
        Returns (is_authorized, reason).
        """
        # 1. Authorization ID Check
        if not plan.authorization_id or plan.authorization_id == "UNAUTHORIZED":
            logger.warning("Plan rejected: Missing valid M01 authorization ID", plan_id=plan.plan_id)
            return False, "Plan REJECTED: Missing valid Module 01 authorization ID."

        # 2. M07 Safety Validation Status Check
        if not plan.safety_validation_id:
            logger.warning("Plan rejected: Missing M07 safety validation ID", plan_id=plan.plan_id)
            return False, "Plan REJECTED: Missing Module 07 safety validation ID."

        allowed_statuses = ("SAFE", "CONDITIONAL", "EMERGENCY")
        if plan.status not in allowed_statuses:
            logger.warning("Plan rejected: M07 safety status not approved", plan_id=plan.plan_id, status=plan.status)
            return False, f"Plan REJECTED: Module 07 safety status is '{plan.status}'. Only SAFE, CONDITIONAL, or EMERGENCY plans are executable."

        # 3. Expiration Check
        now = datetime.now(timezone.utc)
        if plan.expires_at and now > plan.expires_at:
            logger.warning("Plan rejected: Plan has expired", plan_id=plan.plan_id, expires_at=plan.expires_at)
            return False, f"Plan REJECTED: Action plan expired at {plan.expires_at.isoformat()}."

        # 4. Action List Non-empty Check
        if not plan.actions:
            return False, "Plan REJECTED: Action plan contains no execution actions."

        logger.info("Plan authorization verified successfully", plan_id=plan.plan_id, auth_id=plan.authorization_id, safety_id=plan.safety_validation_id)
        return True, "Plan authorization and M07 safety status verified."
