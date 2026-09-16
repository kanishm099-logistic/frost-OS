"""
Frost OS Module 05 — Telemetry Processor Tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.config.settings import Settings
from app.core.telemetry_processor import TelemetryProcessor


class TestTelemetryProcessor:
    """Tests for TelemetryProcessor."""

    def setup_method(self):
        self.settings = Settings(
            environment="testing",
            database_url="sqlite+aiosqlite:///:memory:",
            mock_mode=True,
        )
        self.processor = TelemetryProcessor(self.settings)

    def test_ingest_valid_reading(self):
        now = datetime.now(timezone.utc)
        quality = self.processor.ingest_reading("EQ-1", "power_kw", now, 50.0)
        assert quality == "GOOD"

    def test_ingest_out_of_range_returns_bad(self):
        now = datetime.now(timezone.utc)
        quality = self.processor.ingest_reading("EQ-1", "power_kw", now, -999999.0)
        assert quality == "BAD"

    def test_ingest_high_rate_of_change_returns_suspect(self):
        now = datetime.now(timezone.utc)
        self.processor.ingest_reading("EQ-1", "power_kw", now, 50.0)
        quality = self.processor.ingest_reading(
            "EQ-1", "power_kw", now + timedelta(milliseconds=10), 9999.0,
        )
        assert quality == "SUSPECT"

    def test_build_window_produces_signals(self):
        now = datetime.now(timezone.utc)
        for i in range(10):
            ts = now + timedelta(seconds=i * 5)
            self.processor.ingest_reading("EQ-1", "power_kw", ts, 50.0 + i)
            self.processor.ingest_reading("EQ-1", "voltage_v", ts, 400.0 + i * 0.1)

        window = self.processor.build_window("EQ-1", "STATION-1")
        assert window.equipment_id == "EQ-1"
        assert window.station_id == "STATION-1"
        assert window.has_signal("power_kw")
        assert window.has_signal("voltage_v")
        assert window.signal_count == 2

    def test_clean_signal_removes_spikes(self):
        # Need enough surrounding data points so std is non-trivial
        values = np.array([10.0, 10.1, 9.9, 10.2, 10.0, 10000.0, 10.1, 9.8, 10.0])
        cleaned = self.processor._clean_signal(values)
        # The extreme spike (index 5) should be reduced by median filter
        assert cleaned[5] < 10000.0

    def test_clean_signal_interpolates_nan(self):
        values = np.array([10.0, np.nan, 12.0])
        cleaned = self.processor._clean_signal(values)
        assert not np.isnan(cleaned[1])
        assert abs(cleaned[1] - 11.0) < 0.1

    def test_clear_buffer(self):
        now = datetime.now(timezone.utc)
        self.processor.ingest_reading("EQ-1", "power_kw", now, 50.0)
        self.processor.clear_buffer("EQ-1")
        window = self.processor.build_window("EQ-1", "STATION-1")
        assert window.signal_count == 0

    def test_batch_ingest(self):
        now = datetime.now(timezone.utc)
        readings = [
            {"signal_name": "power_kw", "value": 50.0, "timestamp": now},
            {"signal_name": "voltage_v", "value": 400.0, "timestamp": now},
        ]
        window = self.processor.ingest_batch("EQ-1", "STATION-1", readings)
        assert window.has_signal("power_kw")
        assert window.has_signal("voltage_v")

    def test_data_quality_insufficient_for_empty(self):
        quality = self.processor.get_data_quality("NONEXISTENT")
        assert quality == "INSUFFICIENT"
