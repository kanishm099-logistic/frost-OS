"""
Frost OS Module 05 — Full Diagnostic Pipeline Tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.config.settings import Settings
from app.core.diagnostic_engine import DiagnosticEngine
from app.models.equipment import Equipment, EquipmentType, OperatingLimits
from app.models.health import DataQuality, HealthState


class TestDiagnosticPipeline:
    """Integration tests for the full diagnostic pipeline."""

    def setup_method(self):
        self.settings = Settings(
            environment="testing",
            database_url="sqlite+aiosqlite:///:memory:",
            mock_mode=True,
        )
        self.engine = DiagnosticEngine(self.settings)

        # Register test equipment
        self.engine.register_equipment(Equipment(
            equipment_id="WT-TEST",
            station_id="STATION-TEST",
            type=EquipmentType.WIND_TURBINE,
            rated_power_kw=120.0,
            operating_limits=OperatingLimits(max_vibration=8.0, max_temperature_c=80.0),
        ))
        self.engine.register_equipment(Equipment(
            equipment_id="BAT-TEST",
            station_id="STATION-TEST",
            type=EquipmentType.BATTERY,
            capacity=6000.0,
            operating_limits=OperatingLimits(
                max_temperature_c=45.0,
                min_temperature_c=-20.0,
            ),
        ))

    def test_normal_wind_returns_healthy(self):
        """Normal wind telemetry should produce HEALTHY result."""
        now = datetime.now(timezone.utc)
        telemetry = []
        for i in range(20):
            ts = now - timedelta(seconds=(20 - i) * 5)
            telemetry.extend([
                {"signal_name": "wind_speed_ms", "value": 8.0 + np.random.normal(0, 0.3), "timestamp": ts},
                {"signal_name": "power_kw", "value": 45.0 + np.random.normal(0, 2), "timestamp": ts},
                {"signal_name": "vibration", "value": 2.0 + np.random.normal(0, 0.1), "timestamp": ts},
                {"signal_name": "rpm", "value": 150.0 + np.random.normal(0, 3), "timestamp": ts},
                {"signal_name": "nacelle_temperature_c", "value": 35.0, "timestamp": ts},
                {"signal_name": "ambient_temperature_c", "value": -10.0, "timestamp": ts},
            ])

        result = self.engine.run_diagnostic("WT-TEST", "STATION-TEST", telemetry)

        assert result.equipment_id == "WT-TEST"
        assert result.health_score >= 70.0
        assert result.data_quality != DataQuality.INSUFFICIENT

    def test_anomalous_wind_detects_issues(self):
        """Anomalous wind telemetry should detect anomalies."""
        now = datetime.now(timezone.utc)
        telemetry = []
        for i in range(20):
            ts = now - timedelta(seconds=(20 - i) * 5)
            telemetry.extend([
                {"signal_name": "wind_speed_ms", "value": 10.0, "timestamp": ts},
                {"signal_name": "power_kw", "value": 5.0, "timestamp": ts},  # Very low for wind speed
                {"signal_name": "vibration", "value": 10.0, "timestamp": ts},  # Above limit
                {"signal_name": "rpm", "value": 3.0, "timestamp": ts},  # Very low
                {"signal_name": "nacelle_temperature_c", "value": 85.0, "timestamp": ts},  # Above limit
                {"signal_name": "ambient_temperature_c", "value": -20.0, "timestamp": ts},
            ])

        result = self.engine.run_diagnostic("WT-TEST", "STATION-TEST", telemetry)

        assert result.anomaly_detected is True
        assert len(result.anomalies) > 0
        assert result.health_score < 100.0

    def test_battery_normal_healthy(self):
        """Normal battery telemetry should produce healthy result."""
        now = datetime.now(timezone.utc)
        telemetry = []
        for i in range(20):
            ts = now - timedelta(seconds=(20 - i) * 5)
            telemetry.extend([
                {"signal_name": "soc_pct", "value": 65.0 - i * 0.1, "timestamp": ts},
                {"signal_name": "voltage_v", "value": 400.0, "timestamp": ts},
                {"signal_name": "current_a", "value": -50.0, "timestamp": ts},
                {"signal_name": "temperature_c", "value": 25.0, "timestamp": ts},
                {"signal_name": "power_kw", "value": 20.0, "timestamp": ts},
            ])

        result = self.engine.run_diagnostic("BAT-TEST", "STATION-TEST", telemetry)
        assert result.health_score >= 70.0

    def test_result_has_all_fields(self):
        """DiagnosticResult should include all expected fields."""
        now = datetime.now(timezone.utc)
        telemetry = [
            {"signal_name": "power_kw", "value": 50.0, "timestamp": now},
        ]
        result = self.engine.run_diagnostic("WT-TEST", "STATION-TEST", telemetry)

        assert result.diagnostic_id is not None
        assert result.equipment_id == "WT-TEST"
        assert result.station_id == "STATION-TEST"
        assert result.timestamp is not None
        assert 0.0 <= result.health_score <= 100.0
        assert result.health_state is not None
        assert result.data_quality is not None
        assert isinstance(result.anomalies, list)
        assert isinstance(result.fault_hypotheses, list)
        assert isinstance(result.recommended_investigation, list)
        assert result.failure_risk is not None

    def test_to_dict_serialization(self):
        """Result should serialize to JSON-compatible dict."""
        now = datetime.now(timezone.utc)
        telemetry = [
            {"signal_name": "power_kw", "value": 50.0, "timestamp": now},
        ]
        result = self.engine.run_diagnostic("WT-TEST", "STATION-TEST", telemetry)
        d = result.to_dict()

        assert "diagnostic_id" in d
        assert "health_score" in d
        assert "anomaly_detected" in d
        assert isinstance(d["anomalies"], list)

    def test_station_health_summary(self):
        """Station-wide health summary should aggregate equipment data."""
        now = datetime.now(timezone.utc)

        # Run diagnostics for both equipment
        self.engine.run_diagnostic("WT-TEST", "STATION-TEST", [
            {"signal_name": "power_kw", "value": 50.0, "timestamp": now},
        ])
        self.engine.run_diagnostic("BAT-TEST", "STATION-TEST", [
            {"signal_name": "soc_pct", "value": 65.0, "timestamp": now},
        ])

        summary = self.engine.get_station_health_summary("STATION-TEST")
        assert summary["station_id"] == "STATION-TEST"
        assert summary["total_equipment"] == 2

    def test_unregistered_equipment_handled(self):
        """Diagnosing unregistered equipment should still work."""
        now = datetime.now(timezone.utc)
        result = self.engine.run_diagnostic("UNKNOWN-EQ", "STATION-TEST", [
            {"signal_name": "power_kw", "value": 50.0, "timestamp": now},
        ])
        assert result.equipment_id == "UNKNOWN-EQ"
        assert result.health_score >= 0.0
