"""
Safety Risk Evaluation Engine.

Evaluates 8 core operational risk categories across validation modes
(NORMAL, CONSERVATIVE, STORM, EMERGENCY).
Does NOT invent probabilities without empirical data evidence.
"""

from __future__ import annotations

from typing import List, Dict, Any, Tuple
import structlog

from app.models.risk import RiskCategory, RiskLevel, RiskAssessmentItem
from app.models.safety_decision import ValidationMode
from app.models.reserve import ReserveCalculation
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class RiskEngine:
    """Safety Risk Assessment Engine."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def evaluate_risks(
        self,
        energy_state: Dict[str, Any],
        forecast: Dict[str, Any],
        reserve_calc: ReserveCalculation,
        equipment_health: Dict[str, Any],
        validation_mode: ValidationMode = ValidationMode.NORMAL,
    ) -> Tuple[List[RiskAssessmentItem], RiskLevel]:
        """
        Evaluates risk across 8 operational categories.
        Returns (list_of_assessments, overall_highest_risk_level).
        """
        items: List[RiskAssessmentItem] = []

        # 1. Energy Shortage Risk
        shortage_prob = float(forecast.get("shortage_probability", 0.05))
        if validation_mode == ValidationMode.STORM:
            shortage_prob *= 1.5
        
        shortage_level = RiskLevel.LOW
        if shortage_prob > 0.40:
            shortage_level = RiskLevel.CRITICAL
        elif shortage_prob > 0.20:
            shortage_level = RiskLevel.HIGH
        elif shortage_prob > 0.10:
            shortage_level = RiskLevel.MEDIUM

        items.append(
            RiskAssessmentItem(
                category=RiskCategory.ENERGY_SHORTAGE_RISK,
                level=shortage_level,
                score=round(shortage_prob * 100.0, 1),
                evidence=[f"M04 Forecast shortage probability: {round(shortage_prob * 100.0, 1)}%"],
                action_required=shortage_level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
            )
        )

        # 2. Reserve Breach Risk
        margin_kwh = reserve_calc.reserve_margin_kwh
        reserve_level = RiskLevel.LOW
        if margin_kwh < 0:
            reserve_level = RiskLevel.CRITICAL
        elif margin_kwh < 50.0:
            reserve_level = RiskLevel.HIGH
        elif margin_kwh < 100.0:
            reserve_level = RiskLevel.MEDIUM

        items.append(
            RiskAssessmentItem(
                category=RiskCategory.RESERVE_BREACH_RISK,
                level=reserve_level,
                score=round(max(0.0, min(100.0, 100.0 - (margin_kwh / 2.0))), 1),
                evidence=[f"Station reserve margin: {margin_kwh} kWh (Satisfied: {reserve_calc.reserve_satisfied})"],
                action_required=reserve_level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
            )
        )

        # 3. Battery Depletion Risk
        soc = float(energy_state.get("battery_soc_pct", 50.0))
        bat_level = RiskLevel.LOW
        if soc <= self.settings.critical_battery_soc_pct:
            bat_level = RiskLevel.CRITICAL
        elif soc <= self.settings.minimum_battery_soc_pct:
            bat_level = RiskLevel.HIGH
        elif soc <= 35.0:
            bat_level = RiskLevel.MEDIUM

        items.append(
            RiskAssessmentItem(
                category=RiskCategory.BATTERY_DEPLETION_RISK,
                level=bat_level,
                score=round(max(0.0, min(100.0, 100.0 - soc)), 1),
                evidence=[f"Current Battery SOC: {soc}% (Minimum: {self.settings.minimum_battery_soc_pct}%)"],
                action_required=bat_level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
            )
        )

        # 4. Hydrogen Depletion Risk
        h2 = float(energy_state.get("hydrogen_level_pct", 60.0))
        h2_level = RiskLevel.LOW
        if h2 <= self.settings.minimum_hydrogen_level_pct:
            h2_level = RiskLevel.HIGH
        elif h2 <= 25.0:
            h2_level = RiskLevel.MEDIUM

        items.append(
            RiskAssessmentItem(
                category=RiskCategory.HYDROGEN_DEPLETION_RISK,
                level=h2_level,
                score=round(max(0.0, min(100.0, 100.0 - h2)), 1),
                evidence=[f"Current Hydrogen Level: {h2}%"],
                action_required=h2_level == RiskLevel.HIGH,
            )
        )

        # 5. Equipment Failure Risk
        overall_health = float(equipment_health.get("overall_health_score", 90.0))
        eq_level = RiskLevel.LOW
        if overall_health < 60.0:
            eq_level = RiskLevel.CRITICAL
        elif overall_health < 75.0:
            eq_level = RiskLevel.HIGH
        elif overall_health < 85.0:
            eq_level = RiskLevel.MEDIUM

        items.append(
            RiskAssessmentItem(
                category=RiskCategory.EQUIPMENT_FAILURE_RISK,
                level=eq_level,
                score=round(100.0 - overall_health, 1),
                evidence=[f"M05 Overall Equipment Health Score: {overall_health}%"],
                action_required=eq_level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
            )
        )

        # 6. Critical Load Loss Risk
        crit_kw = float(energy_state.get("critical_load_kw", self.settings.critical_load_kw))
        gen_kw = float(energy_state.get("current_generation_kw", 50.0))
        load_level = RiskLevel.LOW
        if gen_kw < crit_kw:
            load_level = RiskLevel.HIGH

        items.append(
            RiskAssessmentItem(
                category=RiskCategory.CRITICAL_LOAD_LOSS_RISK,
                level=load_level,
                score=50.0 if load_level == RiskLevel.HIGH else 10.0,
                evidence=[f"Current Generation ({gen_kw} kW) vs Base Critical Load ({crit_kw} kW)"],
                action_required=load_level == RiskLevel.HIGH,
            )
        )

        # 7. Forecast Uncertainty Risk
        conf = float(forecast.get("confidence", 0.85))
        uncert_level = RiskLevel.LOW
        if conf < 0.60:
            uncert_level = RiskLevel.HIGH
        elif conf < 0.75:
            uncert_level = RiskLevel.MEDIUM

        items.append(
            RiskAssessmentItem(
                category=RiskCategory.FORECAST_UNCERTAINTY_RISK,
                level=uncert_level,
                score=round((1.0 - conf) * 100.0, 1),
                evidence=[f"M04 Forecast Model Confidence: {round(conf * 100.0, 1)}%"],
                action_required=uncert_level == RiskLevel.HIGH,
            )
        )

        # 8. Data Quality Risk
        dq = str(energy_state.get("data_quality", "GOOD"))
        dq_level = RiskLevel.LOW
        if dq == "BAD":
            dq_level = RiskLevel.CRITICAL
        elif dq == "STALE":
            dq_level = RiskLevel.HIGH
        elif dq == "DEGRADED":
            dq_level = RiskLevel.MEDIUM

        items.append(
            RiskAssessmentItem(
                category=RiskCategory.DATA_QUALITY_RISK,
                level=dq_level,
                score=90.0 if dq == "BAD" else (60.0 if dq == "STALE" else 10.0),
                evidence=[f"Telemetry Data Quality Status: {dq}"],
                action_required=dq_level in (RiskLevel.HIGH, RiskLevel.CRITICAL),
            )
        )

        # Overall Highest Risk Level Determination
        order = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH, RiskLevel.CRITICAL]
        highest = max(items, key=lambda x: order.index(x.level)).level

        return items, highest
