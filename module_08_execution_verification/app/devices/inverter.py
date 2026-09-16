"""
Station Power Inverter & Converter Device Adapter.
"""

from __future__ import annotations

from typing import Dict, Any
from app.hal.modbus_adapter import ModbusAdapter


class InverterDevice(ModbusAdapter):
    """Inverter hardware device."""

    def __init__(self, device_id: str = "INV-01", endpoint: str = "localhost:502", max_power_kw: float = 300.0):
        caps = {
            "supported_actions": ["SET_INVERTER_POWER"],
            "max_power_kw": max_power_kw,
            "current_power_kw": 90.0,
            "ramp_rate_kw_per_min": 50.0,
        }
        super().__init__(device_id, endpoint, caps)

    async def get_state(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": "INVERTER",
            "online": self.is_connected,
            "power_kw": self.capabilities.get("current_power_kw", 90.0),
            "status": "OPERATIONAL",
        }
