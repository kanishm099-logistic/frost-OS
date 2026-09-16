"""
Frost OS Module 05 — Anomaly Engine Tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.config.settings import Settings
from app.core.anomaly_engine import AnomalyEngine
from app.core.baseline_engine import BaselineEngine
from app.core.telemetry_processor import TelemetryProcessor
from app.equipment.base import SignalData, TelemetryWindow
from app.models.anomaly import AnomalySeverity, AnomalyType
from app.models.equipment import Equipment, EquipmentType, OperatingLimits


class TestAnomalyEngine:
    """Tests for AnomalyEngine."""

    def setup_method(self):
        self.settings = Settings(
            environment="testing",
            database_url="sqlite+aiosqlite:///:memory:",
            mock_mode=True,
        )
        self.baseline_engine = BaselineEngine(self.settings)
        self.engine = AnomalyEngine(self.settings, self.baseline_engine)
        self.equipment = Equipment(
            equipment_id="EQ-TEST",
            station_id="STATION-TEST",
            type=EquipmentType.WIND_TURBINE,
            rated_power_kw=120.0,
        )

    def _make_window(self, signals_data: dict[str, list[float]]) -> TelemetryWindow:
        """Helper to build a TelemetryWindow from signal value lists."""
        now = datetime.now(timezone.utc)
        signals = {}
        for name, values in signals_data.items():
            timestamps = [now - timedelta(seconds=(len(values) - i) * 5) for i in range(len(values))]
            signals[name] = SignalData(
                name=name,
                values=np.array(values),
                timestamps=timestamps,
            )
        return TelemetryWindow(
            equipment_id="EQ-TEST",
            station_id="STATION-TEST",
            signals=signals,
            window_start=now - timedelta(seconds=len(list(signals_data.values())[0]) * 5),
            window_end=now,
        )

    def test_no_anomalies_for_normal_data(self):
        window = self._make_window({
            "power_kw": [50.0 + np.random.normal(0, 1) for _ in range(20)],
            "voltage_v": [400.0 + np.random.normal(0, 0.5) for _ in range(20)],
        })
        anomalies = self.engine.detect_anomalies(window, self.equipment)
        # May have some minor statistical detections but nothing HIGH
        critical = [a for a in anomalies if a.severity in (AnomalySeverity.HIGH, AnomalySeverity.CRITICAL)]
        assert len(critical) == 0

    def test_detects_limit_violation(self):
        window = self._make_window({
            "power_kw": [50.0] * 19 + [999999.0],  # Extreme value at end
        })
        anomalies = self.engine.detect_anomalies(window, self.equipment)
        limit_violations = [a for a in anomalies if a.type == AnomalyType.LIMIT_VIOLATION]
        assert len(limit_violations) > 0

    def test_detects_rate_of_change(self):
        # Large jump in adjacent values
        values = [50.0] * 18 + [50.0, 9990.0]
        window = self._make_window({"power_kw": values})
        anomalies = self.engine.detect_anomalies(window, self.equipment)
        roc = [a for a in anomalies if a.type == AnomalyType.RATE_OF_CHANGE]
        assert len(roc) > 0

    def test_detects_statistical_outlier(self):
        values = [50.0] * 19 + [200.0]  # One outlier
        window = self._make_window({"power_kw": values})
        anomalies = self.engine.detect_anomalies(window, self.equipment)
        stat = [a for a in anomalies if a.type == AnomalyType.STATISTICAL]
        assert len(stat) > 0

    def test_deduplicates_anomalies(self):
        # Same signal, same type should be deduplicated
        values = [50.0] * 19 + [999999.0]
        window = self._make_window({"power_kw": values})
        anomalies = self.engine.detect_anomalies(window, self.equipment)

        # Count unique signal+type combinations
        keys = set(f"{a.type.value}:{','.join(a.signals)}" for a in anomalies)
        assert len(anomalies) == len(keys)

    def test_severity_ordering(self):
        """Anomalies should be sorted highest severity first."""
        values = [50.0] * 18 + [50.0, 999999.0]
        window = self._make_window({"power_kw": values})
        anomalies = self.engine.detect_anomalies(window, self.equipment)

        if len(anomalies) >= 2:
            severity_ranks = [self.engine._severity_rank(a.severity) for a in anomalies]
            assert severity_ranks == sorted(severity_ranks, reverse=True)

    def test_residual_check_with_baseline(self):
        # Set up a baseline
        self.baseline_engine.create_default_baseline("EQ-TEST", EquipmentType.WIND_TURBINE)

        # Create window with value far from baseline
        values = [200.0] * 20  # Way above baseline mean of 60
        window = self._make_window({"power_kw": values})
        anomalies = self.engine.detect_anomalies(window, self.equipment)
        residual = [a for a in anomalies if a.type == AnomalyType.RESIDUAL_DEVIATION]
        assert len(residual) > 0
