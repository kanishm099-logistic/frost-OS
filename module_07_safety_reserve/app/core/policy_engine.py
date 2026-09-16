"""
Versioned Policy Enforcement Engine.

Provides access to versioned and audited safety, reserve, mission, and equipment policies.
"""

from __future__ import annotations

from typing import Dict, Any
import structlog

from policies.reserve_policy import ReservePolicy
from policies.mission_policy import MissionPolicy
from policies.equipment_policy import EquipmentPolicy
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class PolicyEngine:
    """Policy Management & Auditing Engine."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.reserve_policy = ReservePolicy(policy_version=settings.policy_version)
        self.mission_policy = MissionPolicy(policy_version=settings.policy_version)
        self.equipment_policy = EquipmentPolicy(policy_version=settings.policy_version)

    def get_active_policy_summary(self) -> Dict[str, Any]:
        """Return full active policy parameter configuration dictionary."""
        return {
            "policy_version": self.settings.policy_version,
            "station_id": self.settings.station_id,
            "reserve_policy": self.reserve_policy.model_dump(),
            "mission_policy": self.mission_policy.model_dump(),
            "equipment_policy": self.equipment_policy.model_dump(),
        }
