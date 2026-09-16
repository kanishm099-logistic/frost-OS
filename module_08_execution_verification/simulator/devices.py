"""
Simulated Hardware Device Models.
"""

from __future__ import annotations

from typing import Dict, Any


class SimulatedDevice:
    """Simulated hardware device node."""

    def __init__(self, device_id: str, device_type: str, max_power_kw: float = 250.0):
        self.device_id = device_id
        self.device_type = device_type
        self.max_power_kw = max_power_kw
        self.power_kw = 0.0
        self.soc_pct = 60.0
        self.is_online = True
        self.fault_injected = False

    def get_state(self) -> Dict[str, Any]:
        if not self.is_online or self.fault_injected:
            return {
                "device_id": self.device_id,
                "power_kw": 0.0,
                "soc_pct": self.soc_pct,
                "status": "FAULT" if self.fault_injected else "OFFLINE",
                "telemetry_quality": "BAD",
            }
        return {
            "device_id": self.device_id,
            "power_kw": self.power_kw,
            "soc_pct": self.soc_pct,
            "status": "OPERATIONAL",
            "telemetry_quality": "GOOD",
        }
