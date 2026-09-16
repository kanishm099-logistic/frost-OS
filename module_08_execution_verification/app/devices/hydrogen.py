"""
Hydrogen Fuel Cell & Electrolyzer Device Adapter.
"""

from __future__ import annotations

from typing import Dict, Any
from app.hal.opcua_adapter import OPCUAAdapter


class HydrogenDevice(OPCUAAdapter):
    """Hydrogen storage and fuel cell device."""

    def __init__(self, device_id: str = "H2-01", endpoint: str = "opc.tcp://localhost:4840", max_power_kw: float = 100.0):
        caps = {
            "supported_actions": ["USE_HYDROGEN", "HOLD_HYDROGEN"],
            "max_power_kw": max_power_kw,
            "current_power_kw": 0.0,
            "level_pct": 70.0,
        }
        super().__init__(device_id, endpoint, caps)

    async def get_state(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": "HYDROGEN",
            "online": self.is_connected,
            "power_kw": self.capabilities.get("current_power_kw", 0.0),
            "level_pct": self.capabilities.get("level_pct", 70.0),
            "status": "OPERATIONAL",
        }
