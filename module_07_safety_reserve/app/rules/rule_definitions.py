"""
Declarative Safety Rules Registry.
"""

from __future__ import annotations

from typing import List, Dict, Any
from app.models.safety_rule import ConstraintCategory, ConstraintSeverity


RULE_REGISTRY: List[Dict[str, Any]] = [
    {
        "rule_id": "RULE-SOC-01",
        "name": "Battery Minimum SOC Threshold",
        "category": ConstraintCategory.STORAGE.value,
        "severity": ConstraintSeverity.HARD.value,
        "description": "Battery State of Charge must remain at or above the minimum configured protected limit.",
    },
    {
        "rule_id": "RULE-RES-01",
        "name": "Protected Energy Reserve Requirement",
        "category": ConstraintCategory.ENERGY.value,
        "severity": ConstraintSeverity.HARD.value,
        "description": "Total available storage must satisfy the combined 5-component station reserve requirement.",
    },
    {
        "rule_id": "RULE-PWR-01",
        "name": "Microgrid Power Balance Limit",
        "category": ConstraintCategory.POWER.value,
        "severity": ConstraintSeverity.HARD.value,
        "description": "Station load demand must not exceed available generation plus discharge capacity.",
    },
    {
        "rule_id": "RULE-MIS-P0",
        "name": "P0 Life Support Minimum Power Protection",
        "category": ConstraintCategory.MISSION.value,
        "severity": ConstraintSeverity.HARD.value,
        "description": "P0 life support and thermal maintenance workloads must receive 100% of minimum required power.",
    },
    {
        "rule_id": "RULE-MIS-P1",
        "name": "P1 Mission Safe Power Protection",
        "category": ConstraintCategory.MISSION.value,
        "severity": ConstraintSeverity.HARD.value,
        "description": "P1 critical research must not be curtailed below minimum safe operating power without explicit mode declaration.",
    },
    {
        "rule_id": "RULE-DATA-01",
        "name": "Telemetry Data Quality Requirement",
        "category": ConstraintCategory.DATA_QUALITY.value,
        "severity": ConstraintSeverity.HARD.value,
        "description": "Telemetry status must be GOOD. Stale or BAD telemetry triggers immediate fail-safe action.",
    },
]


def list_registered_rules() -> List[Dict[str, Any]]:
    """Return all declarative safety rules."""
    return RULE_REGISTRY
