"""
Frost OS Module 02 — Structured Mission Profile Model.

This is the primary data exchange contract consumed by Module 06
(Optimization Intelligence) and Module 01 (Frost Orchestrator).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.mission import Flexibility, MissionType, MissionState
from app.models.priority import PriorityLevel


class MissionProfile(BaseModel):
    """
    Standardized mission profile consumed by Module 06 Optimization.

    Guarantees:
    1. min_power_kw is explicitly defined and immutable.
    2. Power (kW) and energy (kWh) are explicitly separated.
    3. Buffer is calculated in kWh and added to base energy as protected_energy_kwh.
    4. Flexibility flags (interruptible, shiftable) are explicit booleans.
    """
    mission_id: str = Field(..., description="Unique mission identifier")
    name: str = Field(..., description="Mission display name")
    station_id: str = Field(..., description="Station identifier")
    priority: PriorityLevel = Field(..., description="P0 to P4 priority classification")
    type: MissionType = Field(..., description="Mission functional category")

    # Power requirements (kW)
    required_power_kw: float = Field(..., gt=0.0, description="Nominal operating power in kW")
    min_power_kw: float = Field(..., gt=0.0, description="Minimum safe power threshold in kW")
    max_power_kw: float = Field(..., gt=0.0, description="Peak maximum power limit in kW")

    # Energy requirements (kWh)
    energy_required_kwh: float = Field(..., ge=0.0, description="Estimated base energy in kWh")
    buffer_kwh: float = Field(..., ge=0.0, description="Protected buffer margin in kWh")
    protected_energy_kwh: float = Field(..., ge=0.0, description="Total protected energy requirement in kWh")

    # Time & Scheduling
    expected_duration_minutes: int = Field(..., gt=0, description="Execution duration in minutes")
    deadline: datetime | None = Field(default=None, description="Hard deadline (UTC)")
    flexibility: Flexibility = Field(..., description="Flexibility classification")
    interruptible: bool = Field(default=False, description="Can pause and resume without mission abort")
    shiftable: bool = Field(default=False, description="Can shift start time within planning window")
    earliest_start: datetime | None = Field(default=None, description="Earliest permitted start time (UTC)")
    latest_start: datetime | None = Field(default=None, description="Latest start time to meet deadline (UTC)")

    # Dependencies & Status
    dependencies: list[str] = Field(default_factory=list, description="IDs of prerequisite missions")
    status: MissionState = Field(..., description="Current lifecycle state")

    # Optimization inputs
    scheduling_score: float = Field(default=0.0, ge=0.0, le=100.0, description="Composite urgency/priority score")
    is_protected: bool = Field(default=False, description="True if P0/P1 protected from load shedding")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Extensible contextual metadata")
