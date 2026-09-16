"""
Frost OS Module 03 — MQTT Telemetry Client & Topic Tests.
"""

from __future__ import annotations

import json
import pytest

from app.config.settings import Settings
from app.models.telemetry import DeviceType, MetricType, QualityStatus
from app.mqtt.client import MQTTTelemetryClient
from app.mqtt.topics import build_telemetry_topic, parse_telemetry_topic


def test_build_and_parse_detailed_topic():
    """Verify topic generation and regex parsing for detailed metrics."""
    topic = build_telemetry_topic(
        station_id="halley_vi",
        device_type=DeviceType.SOLAR,
        device_id="pv_array_01",
        metric=MetricType.POWER_KW,
    )
    assert topic == "frost/halley_vi/telemetry/solar/pv_array_01/power_kw"

    parsed = parse_telemetry_topic(topic)
    assert parsed is not None
    assert parsed.station_id == "halley_vi"
    assert parsed.device_type == DeviceType.SOLAR
    assert parsed.device_id == "pv_array_01"
    assert parsed.metric == MetricType.POWER_KW


def test_build_and_parse_device_level_topic():
    """Verify device-level topic generation and parsing."""
    topic = build_telemetry_topic(
        station_id="halley_vi",
        device_type=DeviceType.BATTERY,
        device_id="bess_rack_02",
    )
    assert topic == "frost/halley_vi/telemetry/battery/bess_rack_02"

    parsed = parse_telemetry_topic(topic)
    assert parsed is not None
    assert parsed.station_id == "halley_vi"
    assert parsed.device_type == DeviceType.BATTERY
    assert parsed.device_id == "bess_rack_02"
    assert parsed.metric is None


def test_mqtt_client_message_parsing():
    """Verify MQTT client parses JSON payload into normalized TelemetryRecords."""
    settings = Settings()
    client = MQTTTelemetryClient(settings)

    # 1. Detailed topic with scalar float payload
    topic = "frost/halley_vi/telemetry/wind/wind_turbine_01/power_kw"
    records = client._parse_message(topic, b"185.4")
    assert len(records) == 1
    rec = records[0]
    assert rec.station_id == "halley_vi"
    assert rec.device_id == "wind_turbine_01"
    assert rec.device_type == DeviceType.WIND
    assert rec.metric == MetricType.POWER_KW
    assert rec.value == 185.4
    assert rec.unit == "kW"

    # 2. Multi-metric device payload
    dev_topic = "frost/halley_vi/telemetry/battery/bess_container"
    payload = json.dumps({
        "power_kw": 45.0,
        "temperature_c": -4.2,
        "voltage_v": 400.0,
    }).encode("utf-8")

    dev_records = client._parse_message(dev_topic, payload)
    assert len(dev_records) == 3
    metrics = {r.metric: r.value for r in dev_records}
    assert metrics[MetricType.POWER_KW] == 45.0
    assert metrics[MetricType.TEMPERATURE_C] == -4.2
    assert metrics[MetricType.VOLTAGE_V] == 400.0
