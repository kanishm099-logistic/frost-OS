"""
Frost OS Module 04 — Uncertainty & Prediction Interval Engine.

Calculates expanding lead-time prediction intervals, quantiles (P10, P50, P90),
and confidence metrics penalized by data staleness and sensor outages.
Guarantees physical consistency without reporting false certainty.
"""

from __future__ import annotations

import math
from typing import Any

from app.models.forecast import DataQuality, PredictionInterval


class UncertaintyEstimator:
    """Estimates statistical confidence intervals and adjusts for input degradation."""

    def __init__(self, confidence_half_life_hours: float = 36.0) -> None:
        self.confidence_half_life_hours = confidence_half_life_hours

    def estimate_interval(
        self,
        point_prediction: float,
        lead_time_hours: float,
        base_residual_std: float,
        data_quality: DataQuality = DataQuality.GOOD,
        physical_min: float = 0.0,
        physical_max: float | None = None,
        nominal_coverage: float = 0.80,
    ) -> PredictionInterval:
        """
        Compute P10, P50, P90 bounds with lead-time expansion and data quality penalty.
        For an 80% interval (P10 to P90), z ~ 1.282. For 90%, z ~ 1.645.
        """
        z = 1.282 if nominal_coverage <= 0.80 else 1.645

        # Expanding lead-time error growth: sigma(t) = sigma_0 * sqrt(1 + beta * t)
        beta = 0.12  # Error growth rate
        lead_multiplier = math.sqrt(1.0 + beta * max(0.0, lead_time_hours))

        # Quality penalty multiplier
        quality_penalty_map = {
            DataQuality.GOOD: 1.0,
            DataQuality.ESTIMATED: 1.25,
            DataQuality.DEGRADED: 1.6,
            DataQuality.STALE_INPUT: 2.2,
            DataQuality.CRITICAL_GAP: 3.2,
        }
        quality_mult = quality_penalty_map.get(data_quality, 1.0)

        effective_std = base_residual_std * lead_multiplier * quality_mult

        margin = z * effective_std

        lower = point_prediction - margin
        upper = point_prediction + margin

        # Apply physical boundary post-processing
        lower = max(physical_min, lower)
        point = max(physical_min, point_prediction)
        upper = max(point, upper)

        if physical_max is not None:
            lower = min(physical_max, lower)
            point = min(physical_max, point)
            upper = min(physical_max, upper)

        # Base confidence calculation decaying with lead time: C(t) = C0 * 2^(-t / T_half)
        c0 = 0.92
        time_decay = 2.0 ** (-max(0.0, lead_time_hours) / self.confidence_half_life_hours)

        confidence_reduction_map = {
            DataQuality.GOOD: 1.0,
            DataQuality.ESTIMATED: 0.9,
            DataQuality.DEGRADED: 0.75,
            DataQuality.STALE_INPUT: 0.55,
            DataQuality.CRITICAL_GAP: 0.35,
        }
        conf = c0 * time_decay * confidence_reduction_map.get(data_quality, 1.0)
        conf = max(0.05, min(0.99, round(conf, 3)))

        return PredictionInterval(
            lower_bound=round(lower, 2),
            prediction=round(point, 2),
            upper_bound=round(upper, 2),
            confidence=conf,
        )
