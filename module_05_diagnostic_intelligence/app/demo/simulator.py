"""
Frost OS Module 05 — Diagnostic Data Simulator.

Generates realistic polar station telemetry for testing and
demonstration. Supports normal operations, icing events, battery
degradation, sensor faults, and configurable anomaly injection.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np


class DiagnosticSimulator:
    """
    Generates realistic polar station equipment telemetry.

    Supports scenarios:
    - Normal operations (seasonal variation, day/night cycles)
    - Wind turbine icing
    - Battery thermal stress
    - Solar panel soiling/degradation
    - Sensor faults (stale, noisy, frozen)
    - Hydrogen system anomalies
    """

    def __init__(
        self,
        station_id: str = "FROST-STATION-ALPHA",
        seed: int | None = None,
    ) -> None:
        self.station_id = station_id
        self.rng = np.random.default_rng(seed)
        self.time_step = 0

    def generate_wind_telemetry(
        self,
        equipment_id: str = "WT-001",
        num_readings: int = 60,
        interval_seconds: int = 5,
        scenario: str = "normal",
        start_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Generate wind turbine telemetry."""
        now = start_time or datetime.now(timezone.utc)
        readings: list[dict[str, Any]] = []

        for i in range(num_readings):
            ts = now - timedelta(seconds=(num_readings - i) * interval_seconds)

            if scenario == "normal":
                wind = 6.0 + 4.0 * math.sin(i / 20.0) + self.rng.normal(0, 0.5)
                wind = max(0, wind)
                power = self._wind_power(wind) + self.rng.normal(0, 2)
                vibration = 2.0 + self.rng.normal(0, 0.2)
                rpm = min(300, max(0, wind * 18 + self.rng.normal(0, 3)))
                nacelle_temp = 30.0 + self.rng.normal(0, 1)
                ambient_temp = -8.0 + self.rng.normal(0, 0.5)

            elif scenario == "icing":
                wind = 10.0 + self.rng.normal(0, 0.5)
                power = self._wind_power(wind) * 0.3 + self.rng.normal(0, 2)
                vibration = 4.5 + self.rng.normal(0, 0.5)
                rpm = 50.0 + self.rng.normal(0, 5)
                nacelle_temp = 20.0 + self.rng.normal(0, 1)
                ambient_temp = -18.0 + self.rng.normal(0, 0.3)

            elif scenario == "bearing_wear":
                wind = 8.0 + self.rng.normal(0, 0.5)
                power = self._wind_power(wind) * 0.85 + self.rng.normal(0, 2)
                vibration = 6.0 + i * 0.02 + self.rng.normal(0, 0.3)
                rpm = 140.0 + self.rng.normal(0, 5)
                nacelle_temp = 50.0 + i * 0.1 + self.rng.normal(0, 1)
                ambient_temp = -5.0 + self.rng.normal(0, 0.5)

            else:
                wind = 8.0 + self.rng.normal(0, 1)
                power = self._wind_power(wind) + self.rng.normal(0, 2)
                vibration = 2.0 + self.rng.normal(0, 0.2)
                rpm = 150.0 + self.rng.normal(0, 5)
                nacelle_temp = 35.0 + self.rng.normal(0, 1)
                ambient_temp = -10.0 + self.rng.normal(0, 0.5)

            readings.extend([
                {"signal_name": "wind_speed_ms", "value": round(max(0, wind), 2), "timestamp": ts},
                {"signal_name": "power_kw", "value": round(max(0, power), 2), "timestamp": ts},
                {"signal_name": "vibration", "value": round(max(0, vibration), 3), "timestamp": ts},
                {"signal_name": "rpm", "value": round(max(0, rpm), 1), "timestamp": ts},
                {"signal_name": "nacelle_temperature_c", "value": round(nacelle_temp, 1), "timestamp": ts},
                {"signal_name": "ambient_temperature_c", "value": round(ambient_temp, 1), "timestamp": ts},
            ])

        return readings

    def generate_battery_telemetry(
        self,
        equipment_id: str = "BAT-001",
        num_readings: int = 60,
        interval_seconds: int = 5,
        scenario: str = "normal",
        start_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Generate battery telemetry."""
        now = start_time or datetime.now(timezone.utc)
        readings: list[dict[str, Any]] = []

        base_soc = 70.0

        for i in range(num_readings):
            ts = now - timedelta(seconds=(num_readings - i) * interval_seconds)

            if scenario == "normal":
                soc = base_soc - i * 0.05 + self.rng.normal(0, 0.1)
                voltage = 400.0 + self.rng.normal(0, 1)
                current = -30.0 + self.rng.normal(0, 2)
                temp = 25.0 + self.rng.normal(0, 0.5)
                power = 12.0 + self.rng.normal(0, 1)

            elif scenario == "thermal_stress":
                soc = base_soc - i * 0.1
                voltage = 395.0 + self.rng.normal(0, 3)
                current = -80.0 + self.rng.normal(0, 5)
                temp = 40.0 + i * 0.3 + self.rng.normal(0, 0.5)
                power = 32.0 + self.rng.normal(0, 2)

            elif scenario == "cell_imbalance":
                soc = base_soc - i * 0.08
                voltage = 400.0 + self.rng.normal(0, 5)
                current = -50.0 + self.rng.normal(0, 3)
                temp = 28.0 + self.rng.normal(0, 0.5)
                power = 20.0 + self.rng.normal(0, 1)

            else:
                soc = base_soc - i * 0.05
                voltage = 400.0 + self.rng.normal(0, 1)
                current = -30.0 + self.rng.normal(0, 2)
                temp = 25.0 + self.rng.normal(0, 0.5)
                power = 12.0 + self.rng.normal(0, 1)

            readings.extend([
                {"signal_name": "soc_pct", "value": round(max(0, min(100, soc)), 1), "timestamp": ts},
                {"signal_name": "soh_pct", "value": 95.0, "timestamp": ts},
                {"signal_name": "voltage_v", "value": round(voltage, 1), "timestamp": ts},
                {"signal_name": "current_a", "value": round(current, 1), "timestamp": ts},
                {"signal_name": "temperature_c", "value": round(temp, 1), "timestamp": ts},
                {"signal_name": "power_kw", "value": round(max(0, power), 1), "timestamp": ts},
            ])

        return readings

    def generate_solar_telemetry(
        self,
        equipment_id: str = "SA-001",
        num_readings: int = 60,
        interval_seconds: int = 5,
        scenario: str = "normal",
        start_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Generate solar array telemetry."""
        now = start_time or datetime.now(timezone.utc)
        readings: list[dict[str, Any]] = []

        for i in range(num_readings):
            ts = now - timedelta(seconds=(num_readings - i) * interval_seconds)

            # Simulate time-of-day irradiance
            hour_frac = (i / num_readings) * 12
            irradiance = max(0, 600 * math.sin(math.pi * hour_frac / 12))

            if scenario == "normal":
                irr = irradiance + self.rng.normal(0, 20)
                temp = -5.0 + self.rng.normal(0, 0.5)
                power = max(0, irr * 0.42 * 0.19 / 1000.0 * 1000 + self.rng.normal(0, 1))

            elif scenario == "soiling":
                irr = irradiance + self.rng.normal(0, 20)
                temp = -5.0 + self.rng.normal(0, 0.5)
                power = max(0, irr * 0.42 * 0.19 / 1000.0 * 1000 * 0.65 + self.rng.normal(0, 1))

            else:
                irr = irradiance + self.rng.normal(0, 20)
                temp = -5.0 + self.rng.normal(0, 0.5)
                power = max(0, irr * 0.42 * 0.19 / 1000.0 * 1000 + self.rng.normal(0, 1))

            readings.extend([
                {"signal_name": "irradiance_wm2", "value": round(max(0, irr), 1), "timestamp": ts},
                {"signal_name": "power_kw", "value": round(max(0, power), 2), "timestamp": ts},
                {"signal_name": "temperature_c", "value": round(temp, 1), "timestamp": ts},
            ])

        return readings

    def _wind_power(self, wind_speed: float) -> float:
        """Simplified cubic power curve."""
        cut_in, rated_speed, cut_out, rated_power = 3.0, 12.0, 25.0, 120.0
        if wind_speed < cut_in or wind_speed > cut_out:
            return 0.0
        if wind_speed >= rated_speed:
            return rated_power
        ratio = (wind_speed - cut_in) / (rated_speed - cut_in)
        return rated_power * ratio ** 3
