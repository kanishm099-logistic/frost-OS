"""
Safety Agent — Explanation & Operator Query Layer.

IMPORTANT BOUNDARY CONSTRAINT:
The Safety Agent is purely an EXPLANATION and QUERY layer over deterministic safety services.
It summarizes why a plan passed or failed, formats audit logs, and answers operator queries.
It MUST NOT decide safety outcomes, modify thresholds, or override deterministic rules.
"""

from __future__ import annotations

from typing import Dict, Any, List
import structlog

from app.models.validation import ValidationResult
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class SafetyAgent:
    """Read-only Explanation & Operator Query Agent."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def explain_validation_result(self, res: ValidationResult) -> Dict[str, Any]:
        """
        Generate human-readable operator explanation summarizing deterministic results.
        """
        summary_bullets: List[str] = []

        if res.status.value == "SAFE":
            summary_bullets.append("✅ Plan satisfies all microgrid power, storage, and mission safety constraints.")
            summary_bullets.append(f"🛡️ Protected Reserve: {res.reserve_calculation.total_protected_reserve_kwh} kWh (Available: {res.reserve_calculation.total_available_storage_kwh} kWh, Margin: {res.reserve_calculation.reserve_margin_kwh} kWh).")
            summary_bullets.append(f"⏱️ Time-to-Reserve Horizon: {res.reserve_calculation.time_to_reserve_expected_hours} hours expected ({res.reserve_calculation.time_to_reserve_conservative_hours} hours conservative).")

        elif res.status.value == "CONDITIONAL":
            summary_bullets.append("⚠️ Plan approved with operational conditions / warnings.")
            for v in res.soft_violations:
                summary_bullets.append(f"• Soft Warning [{v.rule_id}]: {v.description}")
            summary_bullets.append(f"📊 Overall Risk Level: {res.overall_risk_level.value}")

        elif res.status.value == "REQUIRES_REPLAN":
            summary_bullets.append("🔄 Plan requires immediate re-optimization (REPLAN).")
            for v in res.hard_violations:
                summary_bullets.append(f"❌ Violation [{v.rule_id}]: {v.description}")

        elif res.status.value == "UNSAFE":
            summary_bullets.append("🚫 Plan REJECTED (UNSAFE). Violates hard microgrid safety boundaries.")
            for reason in res.rejection_reasons:
                summary_bullets.append(f"❌ {reason}")

        elif res.status.value == "EMERGENCY":
            summary_bullets.append("🚨 EMERGENCY CONDITION DETECTED! Hardware protection path activated.")
            summary_bullets.append(f"❌ {res.explanation}")

        return {
            "validation_id": res.validation_id,
            "plan_id": res.plan_id,
            "decision_status": res.status.value,
            "is_executable": res.is_executable,
            "summary_bullets": summary_bullets,
            "policy_version": res.policy_version,
            "deterministic_reasons": res.rejection_reasons,
        }
