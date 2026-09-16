"""
Frost OS Module 05 — Degradation Engine.

Tracks long-term changes in equipment behavior. Distinguishes temporary
anomaly spikes from persistent degradation using linear regression
on windowed health/efficiency history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog

from app.config.settings import Settings

logger = structlog.get_logger(__name__)


@dataclass
class DegradationTrend:
    """Long-term degradation trend for a single metric."""
    equipment_id: str
    metric_name: str
    current_value: float
    baseline_value: float
    degradation_rate_per_month: float
    trend_direction: str  # "stable", "declining", "improving"
    confidence: float
    window_days: float = 30.0
    data_points: int = 0


class DegradationEngine:
    """
    Tracks long-term equipment behavior changes.

    Distinguishes temporary anomaly (spike + recovery) from persistent
    degradation (monotonic decline) using linear regression on windowed
    metric history.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        # metric_history[equipment_id][metric_name] = [(timestamp, value), ...]
        self._metric_history: dict[str, dict[str, list[tuple[datetime, float]]]] = {}
        self._trends: dict[str, dict[str, DegradationTrend]] = {}

    def record_metric(
        self,
        equipment_id: str,
        metric_name: str,
        value: float,
        timestamp: datetime | None = None,
    ) -> None:
        """Record a metric value for degradation tracking."""
        ts = timestamp or datetime.now(timezone.utc)

        if equipment_id not in self._metric_history:
            self._metric_history[equipment_id] = {}
        if metric_name not in self._metric_history[equipment_id]:
            self._metric_history[equipment_id][metric_name] = []

        self._metric_history[equipment_id][metric_name].append((ts, value))

        # Trim to last 1000 entries
        if len(self._metric_history[equipment_id][metric_name]) > 1000:
            self._metric_history[equipment_id][metric_name] = (
                self._metric_history[equipment_id][metric_name][-1000:]
            )

    def compute_degradation(
        self,
        equipment_id: str,
        metric_name: str = "health_score",
        window_days: float = 30.0,
    ) -> DegradationTrend:
        """
        Compute degradation trend for a metric over a time window.

        Uses linear regression to determine direction and rate.
        Distinguishes temporary spikes from persistent trends.
        """
        history = self._metric_history.get(equipment_id, {}).get(metric_name, [])

        if len(history) < 3:
            return DegradationTrend(
                equipment_id=equipment_id,
                metric_name=metric_name,
                current_value=history[-1][1] if history else 0.0,
                baseline_value=history[0][1] if history else 0.0,
                degradation_rate_per_month=0.0,
                trend_direction="stable",
                confidence=0.0,
                window_days=window_days,
                data_points=len(history),
            )

        # Filter to window
        now = datetime.now(timezone.utc)
        cutoff_seconds = window_days * 86400.0
        windowed = [(ts, v) for ts, v in history
                    if (now - ts).total_seconds() < cutoff_seconds]

        if len(windowed) < 3:
            windowed = history[-10:]  # Fall back to last 10 points

        timestamps_seconds = np.array([
            (ts - windowed[0][0]).total_seconds() for ts, v in windowed
        ])
        values = np.array([v for ts, v in windowed])

        # Linear regression
        if len(timestamps_seconds) < 2 or np.std(timestamps_seconds) < 1e-9:
            slope = 0.0
            confidence = 0.0
        else:
            coeffs = np.polyfit(timestamps_seconds, values, 1)
            slope = coeffs[0]  # units per second

            # R² for confidence
            predicted = np.polyval(coeffs, timestamps_seconds)
            ss_res = np.sum((values - predicted) ** 2)
            ss_tot = np.sum((values - np.mean(values)) ** 2)
            r_squared = 1.0 - (ss_res / ss_tot) if ss_tot > 1e-9 else 0.0
            confidence = max(0.0, min(1.0, r_squared))

        # Convert to per-month rate
        seconds_per_month = 30.0 * 86400.0
        rate_per_month = slope * seconds_per_month

        # Determine direction
        if abs(rate_per_month) < 0.1:
            direction = "stable"
        elif rate_per_month < 0:
            direction = "declining"
        else:
            direction = "improving"

        trend = DegradationTrend(
            equipment_id=equipment_id,
            metric_name=metric_name,
            current_value=float(values[-1]),
            baseline_value=float(values[0]),
            degradation_rate_per_month=round(rate_per_month, 4),
            trend_direction=direction,
            confidence=round(confidence, 2),
            window_days=window_days,
            data_points=len(windowed),
        )

        # Cache trend
        if equipment_id not in self._trends:
            self._trends[equipment_id] = {}
        self._trends[equipment_id][metric_name] = trend

        return trend

    def get_all_trends(
        self,
        equipment_id: str,
    ) -> dict[str, DegradationTrend]:
        """Get all tracked degradation trends for an equipment."""
        return self._trends.get(equipment_id, {})

    def get_overall_degradation_rate(
        self,
        equipment_id: str,
    ) -> float:
        """
        Get overall degradation rate as a 0-1 normalized value.

        Combines health_score and efficiency trends if available.
        Returns 0.0 for stable/improving, up to 1.0 for severe degradation.
        """
        trends = self._trends.get(equipment_id, {})

        if not trends:
            return 0.0

        # Primarily use health_score trend
        health_trend = trends.get("health_score")
        if health_trend and health_trend.trend_direction == "declining":
            # Normalize: 0 = no decline, 1 = severe decline (>10 points/month)
            return min(1.0, abs(health_trend.degradation_rate_per_month) / 10.0)

        # Fall back to efficiency trend
        eff_trend = trends.get("efficiency")
        if eff_trend and eff_trend.trend_direction == "declining":
            return min(1.0, abs(eff_trend.degradation_rate_per_month) / 5.0)

        return 0.0

    def is_persistent_degradation(
        self,
        equipment_id: str,
        metric_name: str = "health_score",
        min_confidence: float = 0.5,
    ) -> bool:
        """
        Check if degradation is persistent (not just a temporary spike).

        Requires sustained declining trend with sufficient confidence.
        """
        trend = self._trends.get(equipment_id, {}).get(metric_name)
        if trend is None:
            return False

        return (
            trend.trend_direction == "declining"
            and trend.confidence >= min_confidence
            and trend.data_points >= 5
        )
