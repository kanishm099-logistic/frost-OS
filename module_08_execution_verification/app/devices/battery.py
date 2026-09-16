"""
Battery Energy Storage System (BESS) Hardware Device Adapter.
"""

from __future__ import annotations

from typing import Dict, Any
from app.hal.modbus_adapter import ModbusAdapter


class BatteryDevice(ModbusAdapter):
    """BESS hardware abstraction device."""

    def __init__(self, device_id: str = "BAT-01", endpoint: str = "localhost:502", max_power_kw: float = 250.0):
        caps = {
            "supported_actions": ["CHARGE_BATTERY", "DISCHARGE_BATTERY"],
            "max_power_kw": max_power_kw,
            "min_power_kw": 0.0,
            "min_soc_pct": 20.0,
            "max_soc_pct": 95.0,
            "current_power_kw": 0.0,
            "current_soc_pct": 60.0,
        }
        super().__init__(device_id, endpoint, caps)

    async def get_state(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": "BATTERY",
            "online": self.is_connected,
            "power_kw": self.capabilities.get("current_power_kw", 0.0),
            "soc_pct": self.capabilities.get("current_soc_pct", 60.0),
            "status": "OPERATIONAL",
        }
