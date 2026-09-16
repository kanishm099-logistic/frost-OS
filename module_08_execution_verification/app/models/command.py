"""
Protocol Command and Idempotency Models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class ProtocolCommandModel(BaseModel):
    """Low-level protocol command payload translated by HAL."""
    command_id: str
    idempotency_key: str
    action_id: str
    plan_id: str
    device_id: str
    protocol: str  # "MODBUS_TCP", "OPC_UA", "CAN", "MQTT", "SIMULATED"
    endpoint: str
    command_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 15.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CommandAttemptModel(BaseModel):
    """Record of a hardware command execution attempt."""
    attempt_id: str
    command_id: str
    device_id: str
    protocol: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str  # "SENT", "ACKNOWLEDGED", "TIMEOUT", "FAILED", "REJECTED"
    response_payload: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
