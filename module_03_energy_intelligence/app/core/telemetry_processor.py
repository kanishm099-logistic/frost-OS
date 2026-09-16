"""
Frost OS Module 03 — Telemetry Processor.

Handles timestamp validation, unit normalization, physical range checks,
quality status tagging, and rate-of-change outlier detection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.config.settings import Settings
from app.models.telemetry import (
    DeviceType,
    METRIC_LIMITS,
    MetricType,
    QualityStatus,
    TelemetryRecord,
)

logger = structlog.get_logger(__name__)


class TelemetryProcessor:
    """Validates, normalizes, and assigns quality to incoming sensor telemetry."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        # Cache of previous readings for rate-of-change detection: (device_id, metric) -> (timestamp, value)
        self._history: dict[tuple[str, MetricType], tuple[datetime, float]] = {}

    def normalize_unit_and_value(self, metric: MetricType, value: float, unit: str) -> tuple[float, str]:
        """
        Convert engineering units to standard base units:
        Power -> kW, Energy -> kWh, Temp -> °C, Pressure -> bar
        """
        u = unit.strip().lower()

        if metric in (MetricType.POWER_KW,):
            if u in ("w", "watt", "watts"):
                return value / 1000.0, "kW"
            if u in ("mw", "megawatt", "megawatts"):
                return value * 1000.0, "kW"
            return value, "kW"

        if metric in (MetricType.ENERGY_KWH,):
            if u in ("wh", "watthour", "watthours"):
                return value / 1000.0, "kWh"
            if u in ("mwh", "megawatthour", "megawatthours"):
                return value * 1000.0, "kWh"
            return value, "kWh"

        if metric in (MetricType.TEMPERATURE_C,):
            if u in ("k", "kelvin"):
                return value - 273.15, "°C"
            if u in ("f", "fahrenheit"):
                return (value - 32.0) * (5.0 / 9.0), "°C"
            return value, "°C"

        if metric in (MetricType.PRESSURE_BAR,):
            if u in ("psi",):
                return value * 0.0689476, "bar"
            if u in ("pa", "pascal"):
                return value / 100000.0, "bar"
            if u in ("kpa",):
                return value / 100.0, "bar"
            return value, "bar"

        return value, unit

    def process(self, record: TelemetryRecord) -> TelemetryRecord:
        """
        Execute full validation and normalization on a telemetry record.
        Returns the sanitized, quality-rated record.
        """
        now = datetime.now(timezone.utc)

        # 1. Timestamp Sanity Check (Max 60 seconds into future)
        ts = record.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if (ts - now).total_seconds() > 60.0:
            record.quality = QualityStatus.BAD
            err_msg = "Timestamp is unreasonably in the future"
            record.metadata["validation_error"] = err_msg
            record.metadata["quality_reason"] = err_msg
            return record

        record.timestamp = ts

        # 2. Unit Normalization
        norm_val, norm_unit = self.normalize_unit_and_value(record.metric, record.value, record.unit)
        record.value = round(norm_val, 3)
        record.unit = norm_unit

        # 3. Physical Range Validation
        limits = METRIC_LIMITS.get(record.metric)
        if limits:
            min_val, max_val = limits
            if not (min_val <= record.value <= max_val):
                record.quality = QualityStatus.BAD
                record.metadata["validation_error"] = (
                    f"Value {record.value} {record.unit} exceeds physical limits [{min_val}, {max_val}]"
                )
                return record

        # 4. Rate-of-Change Outlier Detection
        key = (record.device_id, record.metric)
        prev = self._history.get(key)
        if prev:
            prev_ts, prev_val = prev
            dt = (record.timestamp - prev_ts).total_seconds()
            if dt > 0.05:  # Avoid division by near-zero jitter
                rate_of_change = abs(record.value - prev_val) / dt
                if record.metric == MetricType.POWER_KW and rate_of_change > self.settings.max_rate_of_change_kw_per_sec:
                    record.quality = QualityStatus.SUSPECT
                    record.metadata["rate_of_change_anomaly"] = f"{rate_of_change:.1f} kW/s exceeds limit"

        # Update historical cache
        self._history[key] = (record.timestamp, record.value)
        return record

    process_record = process
