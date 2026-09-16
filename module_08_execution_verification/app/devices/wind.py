"""
Wind Turbine Hardware Device Adapter.
"""

from __future__ import annotations

from typing import Dict, Any
from app.hal.can_adapter import CANAdapter


class WindDevice(CANAdapter):
    """Wind turbine hardware device."""

    def __init__(self, device_id: str = "WIND-01", endpoint: str = "vcan0", max_power_kw: float = 120.0):
        caps = {
            "supported_actions": ["CURTAIL_RENEWABLE"],
            "max_power_kw": max_power_kw,
            "current_power_kw": 80.0,
        }
        super().__init__(device_id, endpoint, caps)

    async def get_state(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": "WIND",
            "online": self.is_connected,
            "power_kw": self.capabilities.get("current_power_kw", 80.0),
            "status": "OPERATIONAL",
        }
