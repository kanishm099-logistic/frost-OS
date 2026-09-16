"""
Frost OS Module 05 — Health Engine.

Produces 0-100 health_score with configurable weights and transparent
scoring breakdown. The formula is documented and explainable.
A health score is an engineering indicator, not a guaranteed RUL prediction.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.config.settings import Settings
from app.models.anomaly import Anomaly, AnomalySeverity
from app.models.health import (
    ContributingFactor,
    DataQuality,
    EquipmentHealth,
    HealthState,
    ScoringBreakdown,
)

logger = structlog.get_logger(__name__)

# Severity weights for anomaly penalty calculation
SEVERITY_WEIGHTS: dict[AnomalySeverity, float] = {
    AnomalySeverity.INFO: 1.0,
    AnomalySeverity.LOW: 3.0,
    AnomalySeverity.MEDIUM: 8.0,
    AnomalySeverity.HIGH: 18.0,
    AnomalySeverity.CRITICAL: 35.0,
}


class HealthEngine:
    """
    Computes equipment health scores with transparent, configurable scoring.

    Formula:
        score = max(0, 100 - anomaly_penalty - residual_penalty
                     - degradation_penalty + maintenance_bonus)

    Weights and thresholds are configurable via Settings.
    Health state is mapped from score:
        ≥ 85 → HEALTHY
        ≥ 70 → MONITORED
        ≥ 50 → DEGRADED
        ≥ 30 → AT_RISK
        < 30 → CRITICAL
        Insufficient data → UNKNOWN
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._health_history: dict[str, list[EquipmentHealth]] = {}

    def compute_health(
        self,
        equipment_id: str,
        station_id: str,
        anomalies: list[Anomaly],
        residual_magnitude: float = 0.0,
        degradation_rate: float = 0.0,
        last_maintenance: datetime | None = None,
        data_quality: DataQuality = DataQuality.GOOD,
    ) -> EquipmentHealth:
        """
        Compute equipment health score from diagnostic evidence.

        Args:
            anomalies: Currently active anomalies for this equipment
            residual_magnitude: Average |residual| as fraction (0.0-1.0)
            degradation_rate: Long-term degradation rate (0.0-1.0 per year)
            last_maintenance: Most recent maintenance timestamp
            data_quality: Quality of input data
        """
        now = datetime.now(timezone.utc)
        factors: list[ContributingFactor] = []

        # 1. Anomaly penalty — weighted sum of active anomaly severities
        anomaly_penalty = self._compute_anomaly_penalty(anomalies, now)
        factors.append(ContributingFactor(
            factor="anomaly_penalty",
            value=anomaly_penalty,
            description=f"Weighted severity of {len(anomalies)} active anomalies",
            weight=self.settings.health_weight_anomaly,
        ))

        # 2. Residual penalty — persistent deviation from expected behavior
        residual_penalty = min(30.0, residual_magnitude * 100.0 * 0.5)
        factors.append(ContributingFactor(
            factor="residual_penalty",
            value=residual_penalty,
            description=f"Condition-adjusted residual magnitude: {residual_magnitude:.3f}",
            weight=self.settings.health_weight_residual,
        ))

        # 3. Degradation penalty — long-term trend
        degradation_penalty = min(25.0, degradation_rate * 100.0)
        factors.append(ContributingFactor(
            factor="degradation_penalty",
            value=degradation_penalty,
            description=f"Long-term degradation rate: {degradation_rate:.4f}/year",
            weight=self.settings.health_weight_degradation,
        ))

        # 4. Maintenance bonus — recent service improves confidence
        maintenance_bonus = 0.0
        if last_maintenance is not None:
            days_since = (now - last_maintenance).total_seconds() / 86400.0
            if days_since < 30:
                maintenance_bonus = 5.0 * (1.0 - days_since / 30.0)
            elif days_since < 90:
                maintenance_bonus = 2.0 * (1.0 - days_since / 90.0)
        factors.append(ContributingFactor(
            factor="maintenance_bonus",
            value=maintenance_bonus,
            description=f"Recent maintenance credit",
            weight=self.settings.health_weight_maintenance,
        ))

        # Apply weighted formula
        weighted_anomaly = anomaly_penalty * self.settings.health_weight_anomaly
        weighted_residual = residual_penalty * self.settings.health_weight_residual
        weighted_degrad = degradation_penalty * self.settings.health_weight_degradation
        weighted_maint = maintenance_bonus * self.settings.health_weight_maintenance

        final_score = max(0.0, min(100.0,
            100.0 - weighted_anomaly - weighted_residual - weighted_degrad + weighted_maint
        ))

        # Data quality penalty
        confidence = 1.0
        if data_quality == DataQuality.DEGRADED:
            confidence = 0.7
        elif data_quality == DataQuality.ESTIMATED:
            confidence = 0.5
        elif data_quality == DataQuality.STALE_INPUT:
            confidence = 0.4
        elif data_quality == DataQuality.INSUFFICIENT:
            confidence = 0.1
            final_score = 50.0  # Don't claim health when data is missing

        # Map to health state
        health_state = self._score_to_state(final_score, data_quality)

        breakdown = ScoringBreakdown(
            base_score=100.0,
            anomaly_penalty=weighted_anomaly,
            residual_penalty=weighted_residual,
            degradation_penalty=weighted_degrad,
            maintenance_bonus=weighted_maint,
            final_score=final_score,
        )

        health = EquipmentHealth(
            equipment_id=equipment_id,
            station_id=station_id,
            timestamp=now,
            health_score=round(final_score, 1),
            health_state=health_state,
            contributing_factors=factors,
            scoring_breakdown=breakdown,
            data_quality=data_quality,
            confidence=round(confidence, 2),
            anomaly_count=len(anomalies),
        )

        # Track history
        if equipment_id not in self._health_history:
            self._health_history[equipment_id] = []
        self._health_history[equipment_id].append(health)
        # Keep last 100 entries
        if len(self._health_history[equipment_id]) > 100:
            self._health_history[equipment_id] = self._health_history[equipment_id][-100:]

        return health

    def _compute_anomaly_penalty(
        self,
        anomalies: list[Anomaly],
        now: datetime,
    ) -> float:
        """
        Compute anomaly penalty with time decay.

        Recent anomalies get full weight; older anomalies decay
        with half-life specified in settings.
        """
        if not anomalies:
            return 0.0

        half_life_seconds = self.settings.health_anomaly_decay_hours * 3600.0
        total_penalty = 0.0

        for a in anomalies:
            severity_weight = SEVERITY_WEIGHTS.get(a.severity, 1.0)

            # Time decay
            age_seconds = max(0.0, (now - a.timestamp).total_seconds())
            decay = math.exp(-0.693 * age_seconds / half_life_seconds)

            # Score-weighted penalty
            penalty = severity_weight * a.score * decay
            total_penalty += penalty

        return min(100.0, total_penalty)

    def _score_to_state(
        self,
        score: float,
        data_quality: DataQuality,
    ) -> HealthState:
        """Map health score to state, respecting data quality."""
        if data_quality == DataQuality.INSUFFICIENT:
            return HealthState.UNKNOWN

        if score >= self.settings.health_threshold_healthy:
            return HealthState.HEALTHY
        if score >= self.settings.health_threshold_monitored:
            return HealthState.MONITORED
        if score >= self.settings.health_threshold_degraded:
            return HealthState.DEGRADED
        if score >= self.settings.health_threshold_at_risk:
            return HealthState.AT_RISK
        return HealthState.CRITICAL

    def get_health_history(
        self,
        equipment_id: str,
        limit: int = 50,
    ) -> list[EquipmentHealth]:
        """Retrieve health assessment history for an equipment."""
        history = self._health_history.get(equipment_id, [])
        return history[-limit:]

    def get_health_trend(
        self,
        equipment_id: str,
    ) -> dict[str, Any]:
        """Compute health score trend direction and rate."""
        history = self._health_history.get(equipment_id, [])
        if len(history) < 2:
            return {"direction": "stable", "rate": 0.0, "samples": len(history)}

        recent = history[-10:]
        scores = [h.health_score for h in recent]

        if len(scores) >= 2:
            trend = scores[-1] - scores[0]
            rate = trend / len(scores)
            direction = "improving" if rate > 0.5 else "declining" if rate < -0.5 else "stable"
        else:
            direction = "stable"
            rate = 0.0

        return {"direction": direction, "rate": round(rate, 2), "samples": len(scores)}
