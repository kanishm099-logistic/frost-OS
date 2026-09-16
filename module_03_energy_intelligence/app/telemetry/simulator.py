"""
Frost OS Module 03 — Polar Station Telemetry Simulator.

Simulates physical microgrid telemetry for Antarctic polar stations (e.g. Halley VI).
Generates benchmark scenarios:
- Solar: ~120 kW
- Wind: ~180 kW
- Total Load: ~340 kW
- Net Power Balance: ~ -40 kW (deficit requiring battery support)
- Battery: SOC 72%, discharging ~40 kW
- Hydrogen: 81% level
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
import random
from typing import Any
import uuid

import structlog

from app.models.telemetry import (
    DeviceType,
    MetricType,
    QualityStatus,
    TelemetryRecord,
)

logger = structlog.get_logger(__name__)


class PolarStationSimulator:
    """
    Simulates high-fidelity microgrid sensors for a polar research station.
    """

    def __init__(
        self,
        station_id: str = "halley_vi",
        base_solar_kw: float = 120.0,
        base_wind_kw: float = 180.0,
        base_load_kw: float = 340.0,
        battery_soc_pct: float = 72.0,
        hydrogen_pct: float = 81.0,
        ambient_temp_c: float = -28.0,
    ):
        self.station_id = station_id
        self.base_solar_kw = base_solar_kw
        self.base_wind_kw = base_wind_kw
        self.base_load_kw = base_load_kw
        self.battery_soc_pct = battery_soc_pct
        self.hydrogen_pct = hydrogen_pct
        self.ambient_temp_c = ambient_temp_c
        self.tick_counter = 0

    def generate_telemetry_batch(
        self,
        anomaly: str | None = None,
        timestamp: datetime | None = None,
    ) -> list[TelemetryRecord]:
        """
        Generate a synchronized snapshot of telemetry records across all devices.
        Supports simulated anomaly injection: 'spike', 'out_of_range', 'generation_drop', etc.
        """
        now = timestamp or datetime.now(timezone.utc)
        self.tick_counter += 1
        records: list[TelemetryRecord] = []

        # 1. Solar generation (diurnal variation + small cloud noise)
        solar_noise = random.uniform(-5.0, 5.0)
        solar_power = max(0.0, self.base_solar_kw + solar_noise)

        # 2. Wind generation (katabatic wind turbulence)
        wind_noise = random.uniform(-10.0, 10.0)
        wind_power = max(0.0, self.base_wind_kw + wind_noise)

        # Apply generation drop anomaly if requested
        if anomaly == "generation_drop":
            wind_power *= 0.2
            solar_power *= 0.3

        records.extend([
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="solar_array_alpha",
                device_type=DeviceType.SOLAR,
                metric=MetricType.POWER_KW,
                value=round(solar_power, 2),
                unit="kW",
                quality=QualityStatus.GOOD,
                source="simulator",
            ),
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="wind_turbines_cluster",
                device_type=DeviceType.WIND,
                metric=MetricType.POWER_KW,
                value=round(wind_power, 2),
                unit="kW",
                quality=QualityStatus.GOOD,
                source="simulator",
            ),
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="wind_turbines_cluster",
                device_type=DeviceType.WIND,
                metric=MetricType.WIND_SPEED_M_S,
                value=round(12.5 + random.uniform(-1.5, 1.5), 1),
                unit="m/s",
                quality=QualityStatus.GOOD,
                source="simulator",
            ),
        ])

        # 3. Station loads (critical life support, ops, scientific labs, heating)
        load_noise = random.uniform(-5.0, 5.0)
        total_load = self.base_load_kw + load_noise

        if anomaly == "load_spike":
            total_load += 150.0

        records.extend([
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="life_support_primary",
                device_type=DeviceType.LOAD,
                metric=MetricType.POWER_KW,
                value=round(total_load * 0.35, 2),
                unit="kW",
                quality=QualityStatus.GOOD,
                source="simulator",
                metadata={"priority": "CRITICAL", "tier": "P0"},
            ),
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="science_lab_instruments",
                device_type=DeviceType.LOAD,
                metric=MetricType.POWER_KW,
                value=round(total_load * 0.30, 2),
                unit="kW",
                quality=QualityStatus.GOOD,
                source="simulator",
                metadata={"priority": "OPERATIONAL", "tier": "P2"},
            ),
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="water_heating_and_thermal",
                device_type=DeviceType.LOAD,
                metric=MetricType.POWER_KW,
                value=round(total_load * 0.20, 2),
                unit="kW",
                quality=QualityStatus.GOOD,
                source="simulator",
                metadata={"priority": "FLEXIBLE", "tier": "P3"},
            ),
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="snow_melter_utility",
                device_type=DeviceType.LOAD,
                metric=MetricType.POWER_KW,
                value=round(total_load * 0.15, 2),
                unit="kW",
                quality=QualityStatus.GOOD,
                source="simulator",
                metadata={"priority": "DEFERRABLE", "tier": "P4"},
            ),
        ])

        # 4. Battery ESS telemetry
        net_gen = solar_power + wind_power
        net_power = net_gen - total_load
        # Deficit -> battery discharging (positive discharge flow)
        bess_power = -net_power if net_power < 0 else 0.0

        if anomaly == "out_of_range":
            bess_soc = 135.0  # Physically impossible > 100%
        elif anomaly == "battery_low":
            bess_soc = 18.0
        else:
            bess_soc = max(10.0, self.battery_soc_pct - (self.tick_counter * 0.01))

        records.extend([
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="bess_main_container",
                device_type=DeviceType.BATTERY,
                metric=MetricType.SOC_PCT,
                value=round(bess_soc, 2),
                unit="%",
                quality=QualityStatus.GOOD,
                source="simulator",
            ),
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="bess_main_container",
                device_type=DeviceType.BATTERY,
                metric=MetricType.POWER_KW,
                value=round(bess_power, 2),
                unit="kW",
                quality=QualityStatus.GOOD,
                source="simulator",
            ),
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="bess_main_container",
                device_type=DeviceType.BATTERY,
                metric=MetricType.TEMPERATURE_C,
                value=round(-5.0 + random.uniform(-0.5, 0.5), 1),
                unit="°C",
                quality=QualityStatus.GOOD,
                source="simulator",
            ),
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="bess_main_container",
                device_type=DeviceType.BATTERY,
                metric=MetricType.VOLTAGE_V,
                value=round(400.0 + random.uniform(-2.0, 2.0), 1),
                unit="V",
                quality=QualityStatus.GOOD,
                source="simulator",
            ),
        ])

        # 5. Hydrogen storage & Fuel Cell
        records.extend([
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="h2_storage_tank",
                device_type=DeviceType.HYDROGEN,
                metric=MetricType.SOC_PCT,
                value=round(self.hydrogen_pct, 1),
                unit="%",
                quality=QualityStatus.GOOD,
                source="simulator",
            ),
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="h2_storage_tank",
                device_type=DeviceType.HYDROGEN,
                metric=MetricType.PRESSURE_BAR,
                value=round(350.0 * (self.hydrogen_pct / 100.0), 1),
                unit="bar",
                quality=QualityStatus.GOOD,
                source="simulator",
            ),
        ])

        # 6. Thermal storage buffer
        records.append(
            TelemetryRecord(
                record_id=str(uuid.uuid4()),
                timestamp=now,
                station_id=self.station_id,
                device_id="thermal_buffer_tank",
                device_type=DeviceType.THERMAL,
                metric=MetricType.TEMPERATURE_C,
                value=round(85.0 + random.uniform(-1.0, 1.0), 1),
                unit="°C",
                quality=QualityStatus.GOOD,
                source="simulator",
            )
        )

        return records


async def run_simulator_demo() -> None:
    """Run an interactive demonstration of the polar microgrid simulation."""
    from app.config.settings import Settings
    from app.core.energy_engine import EnergyEngine

    settings = Settings()
    engine = EnergyEngine(settings)
    sim = PolarStationSimulator(
        station_id="halley_vi",
        base_solar_kw=120.0,
        base_wind_kw=180.0,
        base_load_kw=340.0,
        battery_soc_pct=72.0,
        hydrogen_pct=81.0,
    )

    print("\n" + "=" * 70)
    print("  FROST OS — MODULE 03: ENERGY INTELLIGENCE")
    print("  Polar Microgrid Telemetry Benchmark Demonstration")
    print("=" * 70)

    # 1. Nominal scenario (Solar 120 kW, Wind 180 kW, Load 340 kW -> -40 kW deficit)
    batch = sim.generate_telemetry_batch()
    state, alerts = engine.process_telemetry_sync(batch)

    print(f"\n[Scenario 1: Baseline Antarctic Operations]")
    print(f"Station:            {state.station_id}")
    print(f"Status:             {state.status.value}")
    print(f"Solar Generation:   {state.generation.solar_kw:.1f} kW ({state.generation.solar_pct:.1f}%)")
    print(f"Wind Generation:    {state.generation.wind_kw:.1f} kW ({state.generation.wind_pct:.1f}%)")
    print(f"Total Generation:   {state.generation.total_generation_kw:.1f} kW")
    print(f"Total Station Load: {state.load.total_load_kw:.1f} kW")
    print(f"Net Power Balance:  {state.net_power_kw:+.1f} kW ({'DEFICIT' if state.net_power_kw < 0 else 'SURPLUS'})")
    print(f"Battery SOC:        {state.battery.soc_pct:.1f}%")
    print(f"Battery Usable:     {state.battery.usable_energy_kwh:.1f} kWh")
    print(f"Battery Runway:     {state.battery.runway_hours:.2f} hours")
    print(f"Hydrogen Usable:    {state.hydrogen.usable_energy_kwh:.1f} kWh")
    print(f"Total Stored Energy:{state.available_stored_energy_kwh:.1f} kWh")
    print(f"Data Quality:       {state.data_quality.value}")
    print(f"Active Alerts:      {state.active_alerts or 'None (nominal)'}")

    # 2. Anomaly scenario: Generation Drop (blizzard/cloud cover)
    print(f"\n[Scenario 2: Sudden Generation Drop]")
    batch_anomaly = sim.generate_telemetry_batch(anomaly="generation_drop")
    state_anom, alerts_anom = engine.process_telemetry_sync(batch_anomaly)
    print(f"New Total Gen:      {state_anom.generation.total_generation_kw:.1f} kW")
    print(f"New Net Balance:    {state_anom.net_power_kw:+.1f} kW")
    print(f"Status:             {state_anom.status.value}")
    print(f"New Battery Runway: {state_anom.battery.runway_hours:.2f} hours")
    print(f"Triggered Alerts:   {state_anom.active_alerts}")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(run_simulator_demo())
