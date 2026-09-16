"""
Solar PV Array Device Adapter.
"""

from __future__ import annotations

from typing import Dict, Any
from app.hal.mqtt_adapter import MQTTAdapter


class SolarDevice(MQTTAdapter):
    """Solar PV Array device."""

    def __init__(self, device_id: str = "SOLAR-01", endpoint: str = "localhost:1883", max_power_kw: float = 60.0):
        caps = {
            "supported_actions": ["CURTAIL_RENEWABLE"],
            "max_power_kw": max_power_kw,
            "current_power_kw": 30.0,
        }
        super().__init__(device_id, endpoint, caps)

    async def get_state(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": "SOLAR",
            "online": self.is_connected,
            "power_kw": self.capabilities.get("current_power_kw", 30.0),
            "status": "OPERATIONAL",
        }
