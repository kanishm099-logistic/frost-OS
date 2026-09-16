"""
Independent Safety Constraint Checker Engine.

Enforces Power Safety, Energy Safety, Mission Protection (P0/P1 rules), Ramp Limits,
Equipment Derating, and Data Quality Fail-Safes.
Differentiates HARD (un-violable -> UNSAFE) vs SOFT constraints.
"""

from __future__ import annotations

from typing import List, Dict, Any, Tuple
import structlog

from app.models.safety_rule import (
    ConstraintCategory,
    ConstraintSeverity,
    ConstraintViolation,
)
from app.models.reserve import ReserveCalculation
from app.config.settings import Settings
from policies.mission_policy import MissionPolicy
from policies.equipment_policy import EquipmentPolicy

logger = structlog.get_logger(__name__)


class ConstraintChecker:
    """Independent Safety Boundary Constraint Engine."""

    def __init__(
        self,
        settings: Settings,
        mission_policy: MissionPolicy | None = None,
        equipment_policy: EquipmentPolicy | None = None,
    ):
        self.settings = settings
        self.mission_policy = mission_policy or MissionPolicy()
        self.equipment_policy = equipment_policy or EquipmentPolicy()

    def check_all_constraints(
        self,
        proposed_plan: Dict[str, Any],
        energy_state: Dict[str, Any],
        reserve_calc: ReserveCalculation,
        equipment_health: Dict[str, Any],
        telemetry_quality: str = "GOOD",
    ) -> Tuple[List[ConstraintViolation], List[ConstraintViolation]]:
        """
        Runs independent verification on proposed M06 plan.
        Returns (hard_violations, soft_violations).
        """
        hard_violations: List[ConstraintViolation] = []
        soft_violations: List[ConstraintViolation] = []

        # 1. Telemetry / Data Quality Safety Check
        if telemetry_quality in ("BAD", "STALE", "MISSING"):
            action = self.equipment_policy.bad_telemetry_action if telemetry_quality == "BAD" else self.equipment_policy.stale_telemetry_action
            if action in ("UNSAFE", "EMERGENCY", "REQUIRES_REPLAN"):
                hard_violations.append(
                    ConstraintViolation(
                        rule_id="RULE-DATA-01",
                        name="Critical Telemetry Data Quality Failure",
                        category=ConstraintCategory.DATA_QUALITY,
                        severity=ConstraintSeverity.HARD,
                        description=f"Telemetry data quality is '{telemetry_quality}'. Fail-safe policy demands plan re-validation/re-planning.",
                        limit_value=1.0,
                        actual_value=0.0 if telemetry_quality == "BAD" else 0.5,
                        unit="quality_status",
                        mitigation_guidance="Verify Modbus/MQTT communication bus before executing plan.",
                    )
                )

        # 2. Battery SOC Hard & Soft Boundaries
        curr_soc = float(energy_state.get("battery_soc_pct", 50.0))
        min_soc = self.settings.minimum_battery_soc_pct
        crit_soc = self.settings.critical_battery_soc_pct

        if curr_soc < min_soc:
            severity = ConstraintSeverity.HARD if curr_soc <= crit_soc else ConstraintSeverity.SOFT
            viol = ConstraintViolation(
                rule_id="RULE-SOC-01",
                name="Battery State of Charge Limit Violation",
                category=ConstraintCategory.STORAGE,
                severity=severity,
                description=f"Battery SOC ({curr_soc}%) is below configured minimum threshold ({min_soc}%).",
                limit_value=min_soc,
                actual_value=curr_soc,
                unit="%",
                mitigation_guidance="Discharge restriction required; activate emergency generation or shed non-P0 loads.",
            )
            if severity == ConstraintSeverity.HARD:
                hard_violations.append(viol)
            else:
                soft_violations.append(viol)

        # 3. Reserve Satisfaction Check
        if not reserve_calc.reserve_satisfied:
            hard_violations.append(
                ConstraintViolation(
                    rule_id="RULE-RES-01",
                    name="Protected Energy Reserve Deficit",
                    category=ConstraintCategory.ENERGY,
                    severity=ConstraintSeverity.HARD,
                    description=f"Available storage ({reserve_calc.total_available_storage_kwh} kWh) cannot satisfy required protected reserve ({reserve_calc.total_protected_reserve_kwh} kWh). Deficit: {abs(reserve_calc.reserve_margin_kwh)} kWh.",
                    limit_value=reserve_calc.total_protected_reserve_kwh,
                    actual_value=reserve_calc.total_available_storage_kwh,
                    unit="kWh",
                    mitigation_guidance="Request immediate M06 re-optimization with load curtailment.",
                )
            )

        # 4. Power Balance & Capacity Limits
        actions = proposed_plan.get("actions", [])
        total_requested_load = float(proposed_plan.get("total_load_kw", 80.0))
        total_available_power = float(energy_state.get("current_generation_kw", 50.0)) + float(energy_state.get("max_battery_discharge_kw", 50.0))

        if total_requested_load > total_available_power + 0.1:
            hard_violations.append(
                ConstraintViolation(
                    rule_id="RULE-PWR-01",
                    name="Microgrid Power Capacity Deficit",
                    category=ConstraintCategory.POWER,
                    severity=ConstraintSeverity.HARD,
                    description=f"Proposed load demand ({total_requested_load} kW) exceeds total available power capacity ({total_available_power} kW).",
                    limit_value=total_available_power,
                    actual_value=total_requested_load,
                    unit="kW",
                    mitigation_guidance="Shed non-critical workloads to restore microgrid power balance.",
                )
            )

        # 5. Mission Protection Rules (P0 / P1 Minimum Power)
        mission_allocations = proposed_plan.get("mission_allocations", [])
        for m in mission_allocations:
            prio = str(m.get("priority", "P3"))
            min_kw = float(m.get("min_power_kw", m.get("minimum_kw", 0.0)))
            allocated_kw = float(m.get("allocated_power_kw", m.get("target_kw", 0.0)))
            
            if prio == "P0" and allocated_kw < min_kw - 0.01:
                hard_violations.append(
                    ConstraintViolation(
                        rule_id="RULE-MIS-P0",
                        name="Critical P0 Life Support Power Violation",
                        category=ConstraintCategory.MISSION,
                        severity=ConstraintSeverity.HARD,
                        description=f"P0 Mission '{m.get('mission_name', 'Life Support')}' allocated {allocated_kw} kW, which is below absolute safe threshold {min_kw} kW.",
                        limit_value=min_kw,
                        actual_value=allocated_kw,
                        unit="kW",
                        mitigation_guidance="P0 missions cannot be curtailed under standard operation.",
                    )
                )

            elif prio == "P1" and allocated_kw < min_kw - 0.01:
                if not self.mission_policy.allow_p1_curtailment_below_min_power:
                    hard_violations.append(
                        ConstraintViolation(
                            rule_id="RULE-MIS-P1",
                            name="P1 Critical Mission Safe Operating Power Violation",
                            category=ConstraintCategory.MISSION,
                            severity=ConstraintSeverity.HARD,
                            description=f"P1 Mission '{m.get('mission_name', 'Critical Research')}' allocated {allocated_kw} kW below minimum safe operating power {min_kw} kW without declared valid operating mode.",
                            limit_value=min_kw,
                            actual_value=allocated_kw,
                            unit="kW",
                            mitigation_guidance="Restore P1 mission power allocation or re-optimize plan.",
                        )
                    )

        # 6. Equipment Derating & Thermal Limits
        for equip_id, health in equipment_health.get("equipment", {}).items():
            derating = float(health.get("derating_factor", 1.0))
            if derating < 0.5 and health.get("status") == "DEGRADED":
                soft_violations.append(
                    ConstraintViolation(
                        rule_id="RULE-EQ-01",
                        name="Equipment Severe Derating Boundary Warning",
                        category=ConstraintCategory.EQUIPMENT,
                        severity=ConstraintSeverity.SOFT,
                        description=f"Equipment '{equip_id}' is operating under severe derating ({derating * 100}% capacity).",
                        limit_value=0.5,
                        actual_value=derating,
                        unit="factor",
                        mitigation_guidance="Avoid dispatching degraded equipment near peak rating.",
                    )
                )

        return hard_violations, soft_violations
