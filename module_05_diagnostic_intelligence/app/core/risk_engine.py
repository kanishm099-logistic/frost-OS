"""
Frost OS Module 05 — Risk Engine.

Estimates probability/risk of equipment failure over configurable horizons.
Returns UNKNOWN/INSUFFICIENT_DATA rather than inventing probability when
sufficient historical data does not exist.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import structlog

from app.config.settings import Settings
from app.models.anomaly import Anomaly, AnomalySeverity
from app.models.health import DataQuality
from app.models.risk import (
    DataSufficiency,
    FailureRisk,
    RiskHorizon,
    RiskLevel,
)

logger = structlog.get_logger(__name__)

# Mapping horizons for human-readable labels
HORIZON_LABELS = {
    1.0: "1h", 6.0: "6h", 24.0: "24h", 72.0: "72h", 168.0: "7d",
}


class RiskEngine:
    """
    Estimates equipment failure risk over configurable time horizons.

    Uses exponential hazard model scaled by:
    - Current health score (lower = higher risk)
    - Active anomaly severity
    - Degradation rate
    - Historical fault patterns

    Returns UNKNOWN when insufficient data exists for meaningful estimation.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._risk_history: dict[str, list[FailureRisk]] = {}
        self._observation_counts: dict[str, int] = {}

    def estimate_risk(
        self,
        equipment_id: str,
        station_id: str,
        health_score: float,
        anomalies: list[Anomaly],
        degradation_rate: float = 0.0,
        data_quality: DataQuality = DataQuality.GOOD,
    ) -> FailureRisk:
        """
        Estimate failure risk for an equipment asset.

        The risk model uses a simple exponential hazard:
            λ = base_rate × severity_multiplier × health_multiplier
            P(failure within t hours) = 1 - exp(-λ × t)
        """
        # Track observations
        obs_count = self._observation_counts.get(equipment_id, 0) + 1
        self._observation_counts[equipment_id] = obs_count

        # Determine data sufficiency
        data_sufficiency = self._assess_data_sufficiency(
            obs_count, data_quality,
        )

        if data_sufficiency == DataSufficiency.INSUFFICIENT:
            return self._insufficient_data_result(equipment_id, station_id)

        # Compute hazard rate
        base_rate = self._compute_base_hazard(health_score, anomalies, degradation_rate)

        # Compute per-horizon risks
        horizons: dict[str, RiskHorizon] = {}
        for hours in self.settings.risk_horizons_hours:
            label = HORIZON_LABELS.get(hours, f"{hours}h")
            probability = 1.0 - math.exp(-base_rate * hours)
            probability = min(1.0, max(0.0, probability))

            # Confidence decreases with horizon length
            base_confidence = 0.7 if data_sufficiency == DataSufficiency.SUFFICIENT else 0.4
            horizon_decay = math.exp(-0.01 * hours)
            confidence = base_confidence * horizon_decay

            risk_level = self._probability_to_level(probability)

            horizons[label] = RiskHorizon(
                horizon_label=label,
                horizon_hours=hours,
                probability=round(probability, 4),
                risk_level=risk_level,
                confidence=round(confidence, 2),
            )

        # Overall risk is the 24h horizon risk
        overall_24h = horizons.get("24h")
        overall_level = overall_24h.risk_level if overall_24h else RiskLevel.UNKNOWN
        overall_confidence = overall_24h.confidence if overall_24h else 0.0

        # Compute contributing factors
        factors: list[str] = []
        if health_score < 50:
            factors.append(f"low_health_score({health_score:.0f})")
        if anomalies:
            high_sev = sum(1 for a in anomalies
                          if a.severity in (AnomalySeverity.HIGH, AnomalySeverity.CRITICAL))
            if high_sev > 0:
                factors.append(f"high_severity_anomalies({high_sev})")
        if degradation_rate > 0.01:
            factors.append(f"active_degradation({degradation_rate:.3f})")
        if not factors:
            factors.append("normal_operation")

        risk = FailureRisk(
            equipment_id=equipment_id,
            station_id=station_id,
            timestamp=datetime.now(timezone.utc),
            horizons=horizons,
            overall_risk_level=overall_level,
            confidence=overall_confidence,
            data_sufficiency=data_sufficiency,
            contributing_factors=factors,
        )

        # Track history
        if equipment_id not in self._risk_history:
            self._risk_history[equipment_id] = []
        self._risk_history[equipment_id].append(risk)
        if len(self._risk_history[equipment_id]) > 50:
            self._risk_history[equipment_id] = self._risk_history[equipment_id][-50:]

        return risk

    def _compute_base_hazard(
        self,
        health_score: float,
        anomalies: list[Anomaly],
        degradation_rate: float,
    ) -> float:
        """
        Compute base hazard rate (failures per hour).

        A healthy system with no anomalies has a very low hazard rate.
        Anomalies and low health scores increase it exponentially.
        """
        # Base hazard — healthy equipment has ~0.001% chance per hour
        if health_score >= 85:
            base = 0.00001
        elif health_score >= 70:
            base = 0.0001
        elif health_score >= 50:
            base = 0.0005
        elif health_score >= 30:
            base = 0.002
        else:
            base = 0.01

        # Severity multiplier from active anomalies
        severity_multiplier = 1.0
        for a in anomalies:
            if a.severity == AnomalySeverity.CRITICAL:
                severity_multiplier *= 3.0
            elif a.severity == AnomalySeverity.HIGH:
                severity_multiplier *= 1.8
            elif a.severity == AnomalySeverity.MEDIUM:
                severity_multiplier *= 1.3

        # Degradation contribution
        degradation_multiplier = 1.0 + degradation_rate * 10.0

        return base * severity_multiplier * degradation_multiplier

    def _probability_to_level(self, probability: float) -> RiskLevel:
        """Map failure probability to risk level."""
        if probability < 0.05:
            return RiskLevel.NEGLIGIBLE
        if probability < 0.15:
            return RiskLevel.LOW
        if probability < 0.35:
            return RiskLevel.MODERATE
        if probability < 0.65:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    def _assess_data_sufficiency(
        self,
        observation_count: int,
        data_quality: DataQuality,
    ) -> DataSufficiency:
        """Assess whether enough data exists for risk estimation."""
        if data_quality == DataQuality.INSUFFICIENT:
            return DataSufficiency.INSUFFICIENT
        if observation_count < 5:
            return DataSufficiency.INSUFFICIENT
        if observation_count < 20 or data_quality in (DataQuality.STALE_INPUT, DataQuality.ESTIMATED):
            return DataSufficiency.PARTIAL
        return DataSufficiency.SUFFICIENT

    def _insufficient_data_result(
        self,
        equipment_id: str,
        station_id: str,
    ) -> FailureRisk:
        """Return an honest UNKNOWN result when data is insufficient."""
        horizons: dict[str, RiskHorizon] = {}
        for hours in self.settings.risk_horizons_hours:
            label = HORIZON_LABELS.get(hours, f"{hours}h")
            horizons[label] = RiskHorizon(
                horizon_label=label,
                horizon_hours=hours,
                probability=None,
                risk_level=RiskLevel.UNKNOWN,
                confidence=0.0,
            )

        return FailureRisk(
            equipment_id=equipment_id,
            station_id=station_id,
            timestamp=datetime.now(timezone.utc),
            horizons=horizons,
            overall_risk_level=RiskLevel.UNKNOWN,
            confidence=0.0,
            data_sufficiency=DataSufficiency.INSUFFICIENT,
            contributing_factors=["insufficient_data_for_estimation"],
        )

    def get_risk_history(self, equipment_id: str, limit: int = 20) -> list[FailureRisk]:
        """Retrieve risk estimation history."""
        return self._risk_history.get(equipment_id, [])[-limit:]
