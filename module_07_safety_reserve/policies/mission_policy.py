"""
Versioned Mission Criticality & Protection Policy.
"""

from __future__ import annotations

from typing import Dict
from pydantic import BaseModel, Field


class MissionPolicy(BaseModel):
    """Configurable mission protection policy."""
    policy_version: str = "7.1.0"
    
    # Priority Protection Rules
    # P0: Hard Safety Constraint (Life Support, Core Thermal, Comms)
    # P1: Hard Mission Constraint (Critical Research) unless explicit valid mode
    # P2: Important Operations
    # P3: Flexible Workloads
    # P4: Deferrable Workloads
    
    allow_p0_curtailment: bool = False
    allow_p1_curtailment_below_min_power: bool = False  # Strict rejection unless mode declared
    
    # Priority Buffer Percentages
    priority_buffer_factors: Dict[str, float] = Field(
        default_factory=lambda: {
            "P0": 0.30,  # 30% protected energy buffer
            "P1": 0.20,  # 20% protected energy buffer
            "P2": 0.10,  # 10% protected energy buffer
            "P3": 0.05,  # 5% buffer
            "P4": 0.00,  # No buffer
        }
    )
