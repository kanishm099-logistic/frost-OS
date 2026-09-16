"""
Safety Risk Assessment Models.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Dict, Any
from pydantic import BaseModel, Field


class RiskCategory(str, Enum):
    """Categorized operational risks evaluated by Module 07."""
    ENERGY_SHORTAGE_RISK = "ENERGY_SHORTAGE_RISK"
    RESERVE_BREACH_RISK = "RESERVE_BREACH_RISK"
    BATTERY_DEPLETION_RISK = "BATTERY_DEPLETION_RISK"
    HYDROGEN_DEPLETION_RISK = "HYDROGEN_DEPLETION_RISK"
    EQUIPMENT_FAILURE_RISK = "EQUIPMENT_FAILURE_RISK"
    CRITICAL_LOAD_LOSS_RISK = "CRITICAL_LOAD_LOSS_RISK"
    FORECAST_UNCERTAINTY_RISK = "FORECAST_UNCERTAINTY_RISK"
    DATA_QUALITY_RISK = "DATA_QUALITY_RISK"


class RiskLevel(str, Enum):
    """Qualitative risk severity ratings."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskAssessmentItem(BaseModel):
    """Assessment for a single risk category."""
    category: RiskCategory
    level: RiskLevel
    score: float  # 0.0 to 100.0
    evidence: List[str] = Field(default_factory=list)
    action_required: bool = False
