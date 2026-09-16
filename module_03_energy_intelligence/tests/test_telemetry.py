"""
Frost OS Module 03 — Telemetry Processor & Unit Conversion Tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest

from app.core.telemetry_processor import TelemetryProcessor
from app.models.telemetry import (
    DeviceType,
    MetricType,
    QualityStatus,
    TelemetryRecord,
    TelemetryRecordModel,
)


def test_unit_conversion_watts_to_kw():
    """Test automatic conversion of Watts to kilowatts."""
    processor = TelemetryProcessor()
    now = datetime.now(timezone.utc)
    rec = TelemetryRecord(
        record_id=str(uuid.uuid4()),
        timestamp=now,
        station_id="halley_vi",
        device_id="pv_inverter",
        device_type=DeviceType.SOLAR,
        metric=MetricType.POWER_KW,
        value=50000.0,
        unit="W",
    )
    processed = processor.process_record(rec)
    assert processed.value == 50.0
    assert processed.unit == "kW"
    assert processed.quality == QualityStatus.GOOD


def test_unit_conversion_psi_to_bar():
    """Test conversion of PSI to bar for hydrogen pressure."""
    processor = TelemetryProcessor()
    now = datetime.now(timezone.utc)
    rec = TelemetryRecord(
        record_id=str(uuid.uuid4()),
        timestamp=now,
        station_id="halley_vi",
        device_id="h2_tank",
        device_type=DeviceType.HYDROGEN,
        metric=MetricType.PRESSURE_BAR,
        value=5076.32,
        unit="psi",
    )
    processed = processor.process_record(rec)
    assert round(processed.value, 1) == 350.0
    assert processed.unit == "bar"


def test_unit_conversion_kelvin_to_celsius():
    """Test conversion of Kelvin to Celsius."""
    processor = TelemetryProcessor()
    now = datetime.now(timezone.utc)
    rec = TelemetryRecord(
        record_id=str(uuid.uuid4()),
        timestamp=now,
        station_id="halley_vi",
        device_id="bess_temp",
        device_type=DeviceType.BATTERY,
        metric=MetricType.TEMPERATURE_C,
        value=268.15,
        unit="K",
    )
    processed = processor.process_record(rec)
    assert round(processed.value, 1) == -5.0
    assert processed.unit == "°C"


def test_future_timestamp_tagged_bad_data():
    """Test that timestamps in the future are flagged as BAD_DATA."""
    processor = TelemetryProcessor()
    future_time = datetime.now(timezone.utc) + timedelta(minutes=15)
    rec = TelemetryRecord(
        record_id=str(uuid.uuid4()),
        timestamp=future_time,
        station_id="halley_vi",
        device_id="wind_01",
        device_type=DeviceType.WIND,
        metric=MetricType.POWER_KW,
        value=100.0,
        unit="kW",
    )
    processed = processor.process_record(rec)
    assert processed.quality == QualityStatus.BAD_DATA
    assert "future" in processed.metadata.get("quality_reason", "")


def test_out_of_range_tagged_bad_data():
    """Test that physical out-of-range values (e.g. SOC 140%) are flagged."""
    processor = TelemetryProcessor()
    now = datetime.now(timezone.utc)
    rec = TelemetryRecord(
        record_id=str(uuid.uuid4()),
        timestamp=now,
        station_id="halley_vi",
        device_id="bess_soc",
        device_type=DeviceType.BATTERY,
        metric=MetricType.SOC_PCT,
        value=140.0,
        unit="%",
    )
    processed = processor.process_record(rec)
    assert processed.quality == QualityStatus.BAD_DATA


def test_rate_of_change_spike_tagged_suspect():
    """Test that a massive instantaneous jump in sensor value is flagged SUSPECT."""
    processor = TelemetryProcessor()
    now = datetime.now(timezone.utc)
    rec1 = TelemetryRecord(
        record_id=str(uuid.uuid4()),
        timestamp=now,
        station_id="halley_vi",
        device_id="wind_01",
        device_type=DeviceType.WIND,
        metric=MetricType.POWER_KW,
        value=50.0,
        unit="kW",
    )
    processor.process_record(rec1)

    # 1 second later, jumps to 200 kW (>30% jump per sec)
    rec2 = TelemetryRecord(
        record_id=str(uuid.uuid4()),
        timestamp=now + timedelta(seconds=1),
        station_id="halley_vi",
        device_id="wind_01",
        device_type=DeviceType.WIND,
        metric=MetricType.POWER_KW,
        value=200.0,
        unit="kW",
    )
    processed2 = processor.process_record(rec2)
    assert processed2.quality in (QualityStatus.SUSPECT, QualityStatus.BAD_DATA)


def test_orm_roundtrip():
    """Test conversion between domain TelemetryRecord and ORM TelemetryRecordModel."""
    now = datetime.now(timezone.utc)
    domain = TelemetryRecord(
        record_id=str(uuid.uuid4()),
        timestamp=now,
        station_id="halley_vi",
        device_id="pv_alpha",
        device_type=DeviceType.SOLAR,
        metric=MetricType.POWER_KW,
        value=120.0,
        unit="kW",
        quality=QualityStatus.GOOD,
        source="unit_test",
        metadata={"inverter": "ABB-TRIO"},
    )
    orm = TelemetryRecordModel.from_domain(domain)
    restored = orm.to_domain()

    assert restored.record_id == domain.record_id
    assert restored.station_id == domain.station_id
    assert restored.device_id == domain.device_id
    assert restored.value == domain.value
    assert restored.metadata.get("inverter") == "ABB-TRIO"
