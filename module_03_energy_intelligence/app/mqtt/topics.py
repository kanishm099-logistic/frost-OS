"""
Frost OS Module 03 — MQTT Topic Schema & Utilities.

Standardizes MQTT topics for polar telemetry ingestion:
Pattern: frost/{station_id}/telemetry/{device_type}/{device_id}/{metric}
"""

from __future__ import annotations

import re
from typing import NamedTuple

from app.models.telemetry import DeviceType, MetricType


class ParsedTopic(NamedTuple):
    """Structured representation of a parsed telemetry topic."""
    station_id: str
    device_type: DeviceType
    device_id: str
    metric: MetricType | None = None


# Pattern 1: frost/<station_id>/telemetry/<device_type>/<device_id>/<metric>
TOPIC_REGEX_DETAILED = re.compile(
    r"^frost/([^/]+)/telemetry/([^/]+)/([^/]+)/([^/]+)$"
)

# Pattern 2: frost/<station_id>/telemetry/<device_type>/<device_id>
TOPIC_REGEX_DEVICE = re.compile(
    r"^frost/([^/]+)/telemetry/([^/]+)/([^/]+)$"
)


def build_telemetry_topic(
    station_id: str,
    device_type: DeviceType | str,
    device_id: str,
    metric: MetricType | str | None = None,
) -> str:
    """Build a standardized MQTT telemetry topic string."""
    d_type = (device_type.value if isinstance(device_type, DeviceType) else str(device_type)).lower()
    base = f"frost/{station_id}/telemetry/{d_type}/{device_id}"
    if metric is not None:
        m_type = (metric.value if isinstance(metric, MetricType) else str(metric)).lower()
        return f"{base}/{m_type}"
    return base


def parse_telemetry_topic(topic: str) -> ParsedTopic | None:
    """
    Parse an MQTT topic string into structured components.
    Returns ParsedTopic or None if format is unrecognized.
    """
    m_detailed = TOPIC_REGEX_DETAILED.match(topic)
    if m_detailed:
        station_id, dev_type_str, dev_id, metric_str = m_detailed.groups()
        try:
            d_type = DeviceType(dev_type_str.upper())
        except ValueError:
            return None
        try:
            m_type = MetricType(metric_str.upper())
        except ValueError:
            m_type = None
        return ParsedTopic(
            station_id=station_id,
            device_type=d_type,
            device_id=dev_id,
            metric=m_type,
        )

    m_dev = TOPIC_REGEX_DEVICE.match(topic)
    if m_dev:
        station_id, dev_type_str, dev_id = m_dev.groups()
        try:
            d_type = DeviceType(dev_type_str.upper())
        except ValueError:
            return None
        return ParsedTopic(
            station_id=station_id,
            device_type=d_type,
            device_id=dev_id,
            metric=None,
        )

    return None
