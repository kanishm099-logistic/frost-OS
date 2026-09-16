"""
Station Controllable Workload Device Adapter.
"""

from __future__ import annotations

from typing import Dict, Any
from app.hal.mqtt_adapter import MQTTAdapter


class LoadDevice(MQTTAdapter):
    """Controllable station load device (compute, lab equipment, radar, thermal)."""

    def __init__(self, device_id: str = "LOAD-01", endpoint: str = "localhost:1883", max_power_kw: float = 150.0):
        caps = {
            "supported_actions": ["START_MISSION", "PAUSE_MISSION", "RESUME_MISSION", "DEFER_MISSION", "SET_MISSION_POWER", "RESTORE_LOAD", "REDUCE_LOAD"],
            "max_power_kw": max_power_kw,
            "current_power_kw": 60.0,
        }
        super().__init__(device_id, endpoint, caps)

    async def get_state(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": "LOAD",
            "online": self.is_connected,
            "power_kw": self.capabilities.get("current_power_kw", 60.0),
            "status": "OPERATIONAL",
        }
