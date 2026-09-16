"""
Device Registry & Capabilities Models.
"""

from __future__ import annotations

from enum import Enum
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field


class DeviceProtocolEnum(str, Enum):
    """Supported communication protocols."""
    MODBUS_TCP = "MODBUS_TCP"
    MODBUS_RTU = "MODBUS_RTU"
    OPC_UA = "OPC_UA"
    CAN = "CAN"
    MQTT = "MQTT"
    SIMULATED = "SIMULATED"


class DeviceCapabilityModel(BaseModel):
    """Device boundary capabilities & limits."""
    supported_actions: list[str] = Field(default_factory=list)
    rated_power_kw: float = 100.0
    min_power_kw: float = 0.0
    max_power_kw: float = 100.0
    ramp_rate_kw_per_min: float = 50.0
    min_soc_pct: float = 20.0
    max_soc_pct: float = 95.0
    operating_limits: Dict[str, Any] = Field(default_factory=dict)
    emergency_limits: Dict[str, Any] = Field(default_factory=dict)


class DeviceRecordModel(BaseModel):
    """Device registry record."""
    device_id: str
    station_id: str
    device_type: str  # "BATTERY", "WIND", "SOLAR", "HYDROGEN", "INVERTER", "LOAD"
    protocol: DeviceProtocolEnum
    endpoint: str
    capabilities: DeviceCapabilityModel
    status: str = "ONLINE"  # "ONLINE", "OFFLINE", "DEGRADED", "FAULT"
    last_seen: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    current_state: Dict[str, Any] = Field(default_factory=dict)
