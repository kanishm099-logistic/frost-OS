"""
Telemetry Verification Result Models.
"""

from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class VerificationStatusEnum(str, Enum):
    """Telemetry verification result status."""
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    DEVIATION = "DEVIATION"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


class VerificationResultModel(BaseModel):
    """Detailed result comparing expected vs actual telemetry after execution."""
    verification_id: str
    execution_id: str
    action_id: str
    plan_id: str
    device_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: VerificationStatusEnum
    expected: Dict[str, Any] = Field(default_factory=dict)
    actual: Dict[str, Any] = Field(default_factory=dict)
    error: float = 0.0
    tolerance: float = 5.0
    confidence: float = 1.0
    telemetry_quality: str = "GOOD"
    deviation_type: Optional[str] = None
    description: str = ""
