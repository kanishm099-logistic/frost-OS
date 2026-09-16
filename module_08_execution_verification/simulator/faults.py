"""
Hardware Fault Simulator Utilities.
"""

from __future__ import annotations

from simulator.station import PolarStationSimulator


def inject_battery_comm_loss(station_sim: PolarStationSimulator) -> None:
    """Simulate battery communication loss fault."""
    station_sim.inject_fault("BAT-01")
