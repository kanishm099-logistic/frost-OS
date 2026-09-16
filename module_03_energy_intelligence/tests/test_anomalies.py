"""
Frost OS Module 03 — Anomaly Detection & Alert Generation Tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid
import pytest

from app.core.anomaly_detector import AnomalyDetector
from app.models.energy_state import GenerationBreakdown, LoadBreakdown
from app.models.storage import BatteryState
from app.models.telemetry import (
    DeviceType,
    MetricType,
    QualityStatus,
    TelemetryRecord,
)


def test_stale_sensor_detection():
    """Verify sensors older than 30s are identified as STALE."""
    detector = AnomalyDetector(stale_threshold_seconds=30.0)
    now = datetime.now(timezone.utc)

    fresh_rec = TelemetryRecord(
        record_id=str(uuid.uuid4()),
        timestamp=now - timedelta(seconds=10),
        station_id="halley_vi",
        device_id="wind_01",
        device_type=DeviceType.WIND,
        metric=MetricType.POWER_KW,
        value=180.0,
        unit="kW",
    )
    stale_rec = TelemetryRecord(
        record_id=str(uuid.uuid4()),
        timestamp=now - timedelta(seconds=45),
        station_id="halley_vi",
        device_id="solar_01",
        device_type=DeviceType.SOLAR,
        metric=MetricType.POWER_KW,
        value=120.0,
        unit="kW",
    )

    stale_list = detector.detect_stale_sensors(
        latest_telemetry={"wind_01": fresh_rec, "solar_01": stale_rec},
        current_time=now,
    )
    assert len(stale_list) == 1
    assert stale_list[0]["device_id"] == "solar_01"


def test_power_balance_residual_violation():
    """
    Verify detection of physical conservation of energy violations:
    |P_gen + P_bess_discharge - P_load| > tolerance
    """
    detector = AnomalyDetector(balance_tolerance_pct=5.0)

    # Generation: 300 kW, Load: 340 kW, Battery discharging: 40 kW
    # Total input: 340 kW, Total output: 340 kW -> Residual 0% (Nominal)
    gen = 300.0
    load = 340.0
    storage_flow = 40.0  # +40 discharge
    residual_kw, is_anomaly, msg = detector.check_power_balance_residual(
        generation_kw=gen,
        load_kw=load,
        storage_discharge_kw=storage_flow,
    )
    assert not is_anomaly
    assert residual_kw == 0.0

    # Generation 300 kW, Load 340 kW, Battery discharging 0 kW (unaccounted 40 kW deficit)
    # Residual = 40 kW > 5 kW tolerance -> Violation!
    residual_kw2, is_anomaly2, msg2 = detector.check_power_balance_residual(
        generation_kw=gen,
        load_kw=load,
        storage_discharge_kw=0.0,
    )
    assert is_anomaly2
    assert residual_kw2 == 40.0


def test_battery_low_alert_detection():
    """Verify alert when battery SOC falls below 20%."""
    detector = AnomalyDetector()
    battery = BatteryState(
        soc_pct=18.5,
        soh_pct=95.0,
        voltage_v=390.0,
        current_a=50.0,
        temperature_c=-5.0,
        power_kw=19.5,
        capacity_kwh=600.0,
        usable_energy_kwh=0.0,
        runway_hours=0.5,
    )
    alerts = detector.detect_storage_anomalies(battery)
    assert any("BATTERY_LOW" in a["alert_type"] for a in alerts)
