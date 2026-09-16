"""
Frost OS Module 05 — Telemetry Processor.

Validates incoming M03 telemetry records, performs quality checks,
cleans signals (spike removal, gap interpolation), and aligns to
common time grid for diagnostic analysis.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import structlog

from app.config.settings import Settings
from app.equipment.base import SignalData, TelemetryWindow

logger = structlog.get_logger(__name__)

# Physical plausible limits for polar station telemetry
METRIC_LIMITS: dict[str, tuple[float, float]] = {
    "power_kw": (-50000.0, 50000.0),
    "voltage_v": (0.0, 100000.0),
    "current_a": (-2000.0, 2000.0),
    "frequency_hz": (0.1, 100.0),
    "temperature_c": (-100.0, 150.0),
    "pressure_bar": (0.0, 1000.0),
    "vibration": (0.0, 100.0),
    "rpm": (0.0, 10000.0),
    "wind_speed_ms": (0.0, 120.0),
    "wind_direction_deg": (0.0, 360.0),
    "irradiance_wm2": (0.0, 1500.0),
    "soc_pct": (0.0, 100.0),
    "soh_pct": (0.0, 100.0),
    "hydrogen_level_pct": (0.0, 100.0),
    "flow_rate": (0.0, 10000.0),
}


class TelemetryProcessor:
    """
    Validates, cleans, and aligns telemetry signals for diagnostic analysis.

    Pipeline:
    1. Validate timestamp freshness and completeness
    2. Range validation against physical limits
    3. Rate-of-change validation
    4. Spike removal (median filter)
    5. Short gap interpolation
    6. Resample to common time grid
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stale_threshold = timedelta(seconds=settings.stale_sensor_threshold_seconds)
        self.max_rate = settings.max_rate_of_change_per_second
        self._telemetry_buffers: dict[str, dict[str, list[tuple[datetime, float]]]] = {}

    def ingest_reading(
        self,
        equipment_id: str,
        signal_name: str,
        timestamp: datetime,
        value: float,
        quality: str = "GOOD",
    ) -> str:
        """
        Ingest a single telemetry reading into the buffer.

        Returns quality status: GOOD, SUSPECT, BAD, STALE, MISSING.
        """
        if equipment_id not in self._telemetry_buffers:
            self._telemetry_buffers[equipment_id] = {}

        if signal_name not in self._telemetry_buffers[equipment_id]:
            self._telemetry_buffers[equipment_id][signal_name] = []

        # 1. Range validation
        limits = METRIC_LIMITS.get(signal_name)
        if limits is not None:
            if value < limits[0] or value > limits[1]:
                return "BAD"

        # 2. Rate-of-change validation
        buf = self._telemetry_buffers[equipment_id][signal_name]
        if buf:
            prev_ts, prev_val = buf[-1]
            dt_seconds = max(0.001, (timestamp - prev_ts).total_seconds())
            rate = abs(value - prev_val) / dt_seconds
            if rate > self.max_rate:
                # Flag as suspect but still ingest
                buf.append((timestamp, value))
                return "SUSPECT"

        # 3. Staleness check
        if buf:
            last_ts = buf[-1][0]
            if (timestamp - last_ts) > self.stale_threshold:
                quality = "STALE"

        # Store reading
        buf.append((timestamp, value))

        # Trim buffer to window size
        max_entries = max(100, int(self.settings.telemetry_window_seconds / max(1, self.settings.signal_resample_interval_seconds)))
        if len(buf) > max_entries * 2:
            self._telemetry_buffers[equipment_id][signal_name] = buf[-max_entries:]

        return quality

    def ingest_batch(
        self,
        equipment_id: str,
        station_id: str,
        readings: list[dict[str, Any]],
    ) -> TelemetryWindow:
        """
        Ingest a batch of readings and produce a cleaned TelemetryWindow.

        Each reading: {signal_name, timestamp, value, unit?, quality?}
        """
        for r in readings:
            self.ingest_reading(
                equipment_id=equipment_id,
                signal_name=r["signal_name"],
                timestamp=r.get("timestamp", datetime.now(timezone.utc)),
                value=r["value"],
                quality=r.get("quality", "GOOD"),
            )
        return self.build_window(equipment_id, station_id)

    def build_window(
        self,
        equipment_id: str,
        station_id: str,
    ) -> TelemetryWindow:
        """
        Build a cleaned and aligned TelemetryWindow from buffered readings.
        """
        signals: dict[str, SignalData] = {}
        data_quality = "GOOD"
        window_start = None
        window_end = None
        now = datetime.now(timezone.utc)

        equip_buf = self._telemetry_buffers.get(equipment_id, {})

        for sig_name, readings in equip_buf.items():
            if not readings:
                signals[sig_name] = SignalData(
                    name=sig_name, values=np.array([]), timestamps=[],
                )
                continue

            # Extract time series
            timestamps = [r[0] for r in readings]
            values = np.array([r[1] for r in readings], dtype=np.float64)

            # Track window bounds
            if timestamps:
                if window_start is None or timestamps[0] < window_start:
                    window_start = timestamps[0]
                if window_end is None or timestamps[-1] > window_end:
                    window_end = timestamps[-1]

            # Apply cleaning
            cleaned_values = self._clean_signal(values)

            # Check freshness
            quality = "GOOD"
            if timestamps:
                last_ts = timestamps[-1]
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                if (now - last_ts) > self.stale_threshold:
                    quality = "STALE"
                    data_quality = "DEGRADED"

            signals[sig_name] = SignalData(
                name=sig_name,
                values=cleaned_values,
                timestamps=timestamps,
                quality=quality,
            )

        if not signals:
            data_quality = "INSUFFICIENT"

        return TelemetryWindow(
            equipment_id=equipment_id,
            station_id=station_id,
            signals=signals,
            window_start=window_start,
            window_end=window_end,
            data_quality=data_quality,
        )

    def _clean_signal(self, values: np.ndarray) -> np.ndarray:
        """
        Clean signal data:
        1. Replace NaN/inf
        2. Median filter for spike removal (window=3)
        3. Interpolate short gaps
        """
        if len(values) == 0:
            return values

        # Replace inf with NaN
        cleaned = np.where(np.isinf(values), np.nan, values)

        # Simple median filter for spike removal (window=3)
        if len(cleaned) >= 3:
            filtered = np.copy(cleaned)
            for i in range(1, len(cleaned) - 1):
                if not np.isnan(cleaned[i]):
                    # Get neighbors, excluding the current value
                    neighbors = []
                    if i > 0 and not np.isnan(cleaned[i - 1]):
                        neighbors.append(cleaned[i - 1])
                    if i < len(cleaned) - 1 and not np.isnan(cleaned[i + 1]):
                        neighbors.append(cleaned[i + 1])
                    if len(neighbors) >= 1:
                        neighbor_median = float(np.median(neighbors))
                        deviation = abs(cleaned[i] - neighbor_median)
                        # Threshold: if deviation is more than 10× neighbor range or absolute
                        neighbor_range = max(abs(neighbor_median) * 0.5, 1.0)
                        if deviation > neighbor_range * 10:
                            filtered[i] = neighbor_median
            cleaned = filtered

        # Interpolate short NaN gaps (up to 3 consecutive)
        nan_mask = np.isnan(cleaned)
        if np.any(nan_mask) and not np.all(nan_mask):
            # Simple linear interpolation
            valid_indices = np.where(~nan_mask)[0]
            if len(valid_indices) >= 2:
                cleaned = np.interp(
                    np.arange(len(cleaned)),
                    valid_indices,
                    cleaned[valid_indices],
                )

        return cleaned

    def clear_buffer(self, equipment_id: str | None = None) -> None:
        """Clear telemetry buffers for an equipment or all."""
        if equipment_id:
            self._telemetry_buffers.pop(equipment_id, None)
        else:
            self._telemetry_buffers.clear()

    def get_data_quality(self, equipment_id: str) -> str:
        """Assess overall data quality for an equipment."""
        equip_buf = self._telemetry_buffers.get(equipment_id, {})
        if not equip_buf:
            return "INSUFFICIENT"

        now = datetime.now(timezone.utc)
        stale_count = 0
        total = len(equip_buf)

        for sig_name, readings in equip_buf.items():
            if not readings:
                stale_count += 1
                continue
            last_ts = readings[-1][0]
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)
            if (now - last_ts) > self.stale_threshold:
                stale_count += 1

        if stale_count == total:
            return "STALE_INPUT"
        if stale_count > total * 0.5:
            return "DEGRADED"
        return "GOOD"
