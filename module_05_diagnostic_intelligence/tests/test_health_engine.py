"""
Frost OS Module 05 — Health Engine Tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config.settings import Settings
from app.core.health_engine import HealthEngine
from app.models.anomaly import Anomaly, AnomalySeverity, AnomalyType
from app.models.health import DataQuality, HealthState


class TestHealthEngine:
    """Tests for HealthEngine."""

    def setup_method(self):
        self.settings = Settings(
            environment="testing",
            database_url="sqlite+aiosqlite:///:memory:",
            mock_mode=True,
        )
        self.engine = HealthEngine(self.settings)

    def test_healthy_with_no_anomalies(self):
        health = self.engine.compute_health(
            equipment_id="EQ-1",
            station_id="STATION-1",
            anomalies=[],
        )
        assert health.health_score >= 85.0
        assert health.health_state == HealthState.HEALTHY

    def test_score_decreases_with_anomalies(self):
        anomalies = [
            Anomaly(
                equipment_id="EQ-1",
                station_id="STATION-1",
                type=AnomalyType.LIMIT_VIOLATION,
                severity=AnomalySeverity.HIGH,
                score=0.8,
                confidence=0.9,
                signals=["power_kw"],
            ),
        ]
        health = self.engine.compute_health(
            equipment_id="EQ-1",
            station_id="STATION-1",
            anomalies=anomalies,
        )
        assert health.health_score < 100.0
        assert health.anomaly_count == 1

    def test_critical_with_many_anomalies(self):
        anomalies = [
            Anomaly(
                equipment_id="EQ-1",
                station_id="STATION-1",
                type=AnomalyType.LIMIT_VIOLATION,
                severity=AnomalySeverity.CRITICAL,
                score=0.95,
                confidence=0.9,
                signals=["power_kw"],
            ),
            Anomaly(
                equipment_id="EQ-1",
                station_id="STATION-1",
                type=AnomalyType.RESIDUAL_DEVIATION,
                severity=AnomalySeverity.HIGH,
                score=0.8,
                confidence=0.85,
                signals=["vibration"],
            ),
        ]
        health = self.engine.compute_health(
            equipment_id="EQ-1",
            station_id="STATION-1",
            anomalies=anomalies,
            residual_magnitude=0.3,
            degradation_rate=0.1,
        )
        assert health.health_score < 85.0
        assert health.health_state in (HealthState.MONITORED, HealthState.DEGRADED,
                                        HealthState.AT_RISK, HealthState.CRITICAL)

    def test_unknown_with_insufficient_data(self):
        health = self.engine.compute_health(
            equipment_id="EQ-1",
            station_id="STATION-1",
            anomalies=[],
            data_quality=DataQuality.INSUFFICIENT,
        )
        assert health.health_state == HealthState.UNKNOWN
        assert health.confidence < 0.5

    def test_scoring_breakdown_is_transparent(self):
        health = self.engine.compute_health(
            equipment_id="EQ-1",
            station_id="STATION-1",
            anomalies=[],
        )
        breakdown = health.scoring_breakdown
        assert breakdown.base_score == 100.0
        assert breakdown.final_score >= 0.0
        assert "score" in breakdown.formula.lower()

    def test_contributing_factors_listed(self):
        health = self.engine.compute_health(
            equipment_id="EQ-1",
            station_id="STATION-1",
            anomalies=[],
        )
        factor_names = [f.factor for f in health.contributing_factors]
        assert "anomaly_penalty" in factor_names
        assert "residual_penalty" in factor_names
        assert "degradation_penalty" in factor_names
        assert "maintenance_bonus" in factor_names

    def test_maintenance_bonus_for_recent_service(self):
        recent = datetime.now(timezone.utc) - timedelta(days=7)
        health = self.engine.compute_health(
            equipment_id="EQ-1",
            station_id="STATION-1",
            anomalies=[],
            last_maintenance=recent,
        )
        maint_factor = [f for f in health.contributing_factors if f.factor == "maintenance_bonus"]
        assert len(maint_factor) == 1
        assert maint_factor[0].value > 0

    def test_health_history_tracked(self):
        for _ in range(5):
            self.engine.compute_health("EQ-1", "STATION-1", anomalies=[])
        history = self.engine.get_health_history("EQ-1")
        assert len(history) == 5

    def test_health_trend_computation(self):
        for _ in range(5):
            self.engine.compute_health("EQ-1", "STATION-1", anomalies=[])
        trend = self.engine.get_health_trend("EQ-1")
        assert "direction" in trend
        assert "rate" in trend
