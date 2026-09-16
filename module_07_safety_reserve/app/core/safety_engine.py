"""
Master Safety & Reserve Engine.

Orchestrates the 6-stage Safety State Machine:
RECEIVED -> VALIDATING -> RESERVE_CALCULATION -> CONSTRAINT_CHECK -> RISK_EVALUATION -> DECISION.
Generates deterministic safety decision outputs (SAFE, UNSAFE, CONDITIONAL, REQUIRES_REPLAN, EMERGENCY).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import structlog

from app.models.safety_decision import (
    SafetyState,
    SafetyDecisionStatus,
    ValidationMode,
    StateTransition,
)
from app.models.validation import ValidationResult
from app.core.emergency_engine import EmergencyEngine
from app.core.reserve_engine import ReserveEngine
from app.core.constraint_checker import ConstraintChecker
from app.core.risk_engine import RiskEngine
from app.core.policy_engine import PolicyEngine
from app.core.plan_validator import IndependentPlanValidator
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class SafetyEngine:
    """Master Safety & Reserve Intelligence Coordinator."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.policy_engine = PolicyEngine(settings)
        self.emergency_engine = EmergencyEngine(settings)
        self.reserve_engine = ReserveEngine(settings, self.policy_engine.reserve_policy)
        self.constraint_checker = ConstraintChecker(
            settings,
            self.policy_engine.mission_policy,
            self.policy_engine.equipment_policy,
        )
        self.risk_engine = RiskEngine(settings)

    def validate_plan(
        self,
        proposed_plan: Dict[str, Any],
        energy_state: Dict[str, Any],
        missions: List[Dict[str, Any]],
        forecast: Dict[str, Any],
        equipment_health: Dict[str, Any],
        validation_mode: ValidationMode = ValidationMode.NORMAL,
        weather_event: str = "NORMAL",
    ) -> ValidationResult:
        """
        Execute full deterministic safety evaluation pipeline.
        """
        validation_id = f"VAL-{uuid.uuid4().hex[:8].upper()}"
        plan_id = str(proposed_plan.get("optimization_id", proposed_plan.get("plan_id", f"PLAN-{uuid.uuid4().hex[:6]}")))
        station_id = self.settings.station_id

        transitions: List[StateTransition] = []

        def log_transition(from_s: SafetyState, to_s: SafetyState, reason: str):
            t = StateTransition(from_state=from_s, to_state=to_s, reason=reason)
            transitions.append(t)
            logger.info("Safety State Machine Transition", validation_id=validation_id, from_state=from_s.value, to_state=to_s.value, reason=reason)

        # Stage 1: RECEIVED
        log_transition(SafetyState.RECEIVED, SafetyState.VALIDATING, "Initiating plan validation pipeline")

        # STAGE 1.5: Emergency Condition Check (Zero-LLM Protection)
        emergency_data = self.emergency_engine.check_emergency_conditions(energy_state, equipment_health)
        if emergency_data:
            log_transition(SafetyState.VALIDATING, SafetyState.DECISION, f"EMERGENCY DETECTED: {emergency_data['condition']}")
            res_calc = self.reserve_engine.calculate_reserve(energy_state, missions, forecast, equipment_health, weather_event)
            return ValidationResult(
                validation_id=validation_id,
                plan_id=plan_id,
                station_id=station_id,
                status=SafetyDecisionStatus.EMERGENCY,
                validation_mode=validation_mode,
                policy_version=self.settings.policy_version,
                hard_violations=[],
                soft_violations=[],
                reserve_status="BREACHED",
                power_status="EMERGENCY",
                storage_status="CRITICAL",
                mission_status="COMPROMISED",
                equipment_status="EMERGENCY",
                data_quality_status=str(energy_state.get("data_quality", "GOOD")),
                reserve_calculation=res_calc,
                risk_summary=[],
                required_replan=True,
                is_executable=False,
                explanation=f"EMERGENCY TRIGGERED: {emergency_data['description']}. Protective Action: {emergency_data['protective_action']}.",
                state_transitions=transitions,
                rejection_reasons=[emergency_data['description']],
            )

        # Stage 2: RESERVE_CALCULATION
        log_transition(SafetyState.VALIDATING, SafetyState.RESERVE_CALCULATION, "Calculating dynamic 5-component station reserve")
        reserve_calc = self.reserve_engine.calculate_reserve(energy_state, missions, forecast, equipment_health, weather_event)

        # Stage 3: CONSTRAINT_CHECK
        log_transition(SafetyState.RESERVE_CALCULATION, SafetyState.CONSTRAINT_CHECK, "Running independent boundary constraint checks")
        telemetry_quality = str(energy_state.get("data_quality", "GOOD"))
        hard_viols, soft_viols = self.constraint_checker.check_all_constraints(
            proposed_plan, energy_state, reserve_calc, equipment_health, telemetry_quality
        )

        # Independent Recalculation Check
        recalc_out = IndependentPlanValidator.recalculate_and_validate_plan(proposed_plan, energy_state)
        if not recalc_out["valid"]:
            for err in recalc_out["recalculation_errors"]:
                logger.warning("Independent recalculation mismatch", error=err)

        # Stage 4: RISK_EVALUATION
        log_transition(SafetyState.CONSTRAINT_CHECK, SafetyState.RISK_EVALUATION, "Evaluating 8 operational risk categories")
        risks, overall_risk = self.risk_engine.evaluate_risks(energy_state, forecast, reserve_calc, equipment_health, validation_mode)

        # Stage 5: DECISION
        log_transition(SafetyState.RISK_EVALUATION, SafetyState.DECISION, "Formulating deterministic final safety decision")

        # Decision Matrix Logic
        rejection_reasons = [v.description for v in hard_viols]
        
        if hard_viols:
            # If data quality caused failure, status is REQUIRES_REPLAN, else UNSAFE
            dq_failures = [v for v in hard_viols if v.category.value == "DATA_QUALITY"]
            if dq_failures:
                status = SafetyDecisionStatus.REQUIRES_REPLAN
            else:
                status = SafetyDecisionStatus.UNSAFE
            required_replan = True
            is_executable = False
            explanation = f"Plan REJECTED ({status.value}): {len(hard_viols)} hard constraint violation(s) detected. First reason: {hard_viols[0].description}"

        elif soft_viols or overall_risk.value in ("HIGH", "CRITICAL"):
            status = SafetyDecisionStatus.CONDITIONAL
            required_replan = False
            is_executable = True
            explanation = f"Plan APPROVED WITH CONDITIONS: {len(soft_viols)} soft warning(s) and {overall_risk.value} risk level detected."

        else:
            status = SafetyDecisionStatus.SAFE
            required_replan = False
            is_executable = True
            explanation = "Plan APPROVED (SAFE): Satisfies all station energy reserve requirements, power balances, and equipment safety limits."

        return ValidationResult(
            validation_id=validation_id,
            plan_id=plan_id,
            station_id=station_id,
            status=status,
            validation_mode=validation_mode,
            policy_version=self.settings.policy_version,
            hard_violations=hard_viols,
            soft_violations=soft_viols,
            reserve_status="SATISFIED" if reserve_calc.reserve_satisfied else "BREACHED",
            power_status="NORMAL" if not any(v.category.value == "POWER" for v in hard_viols) else "VIOLATED",
            storage_status="HEALTHY" if not any(v.category.value == "STORAGE" for v in hard_viols) else "DEGRADED",
            mission_status="PROTECTED" if not any(v.category.value == "MISSION" for v in hard_viols) else "COMPROMISED",
            equipment_status="SAFE" if not any(v.category.value == "EQUIPMENT" for v in hard_viols) else "OVERLOADED",
            data_quality_status=telemetry_quality,
            reserve_calculation=reserve_calc,
            risk_summary=risks,
            overall_risk_level=overall_risk,
            required_replan=required_replan,
            is_executable=is_executable,
            explanation=explanation,
            state_transitions=transitions,
            rejection_reasons=rejection_reasons,
        )
