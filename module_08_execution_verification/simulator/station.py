"""
Simulated Polar Research Station Microgrid.
"""

from __future__ import annotations

from typing import Dict, Any
from simulator.devices import SimulatedDevice


class PolarStationSimulator:
    """Complete simulated polar station microgrid hardware bus."""

    def __init__(self, station_id: str = "POLAR-STATION-ALPHA"):
        self.station_id = station_id
        self.devices: Dict[str, SimulatedDevice] = {
            "BAT-01": SimulatedDevice("BAT-01", "BATTERY", max_power_kw=250.0),
            "WIND-01": SimulatedDevice("WIND-01", "WIND", max_power_kw=120.0),
            "SOLAR-01": SimulatedDevice("SOLAR-01", "SOLAR", max_power_kw=60.0),
            "H2-01": SimulatedDevice("H2-01", "HYDROGEN", max_power_kw=100.0),
            "INV-01": SimulatedDevice("INV-01", "INVERTER", max_power_kw=300.0),
            "LOAD-01": SimulatedDevice("LOAD-01", "LOAD", max_power_kw=150.0),
        }

    def inject_fault(self, device_id: str) -> None:
        if device_id in self.devices:
            self.devices[device_id].fault_injected = True
            self.devices[device_id].is_online = False

    def clear_faults(self) -> None:
        for dev in self.devices.values():
            dev.fault_injected = False
            dev.is_online = True
