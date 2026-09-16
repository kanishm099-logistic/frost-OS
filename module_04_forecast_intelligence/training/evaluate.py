"""
Frost OS Module 04 — Model Evaluation & Baseline Comparison.

Calculates standard forecast performance metrics:
- MAE, RMSE, MAPE
- Prediction Interval Coverage Probability (PICP)
- Comparison against naive baselines: Persistence (t - 1) and Rolling Mean (4-step)
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class ForecastEvaluator:
    """Evaluates point predictions and interval coverage against naive baselines."""

    @staticmethod
    def calculate_metrics(
        y_true: np.ndarray | pd.Series,
        y_pred: np.ndarray | pd.Series,
        lower_bound: np.ndarray | pd.Series | None = None,
        upper_bound: np.ndarray | pd.Series | None = None,
    ) -> dict[str, float]:
        """Compute MAE, RMSE, MAPE, and interval coverage percentage."""
        y_t = np.asarray(y_true, dtype=float)
        y_p = np.asarray(y_pred, dtype=float)

        mae = float(np.mean(np.abs(y_t - y_p)))
        rmse = float(np.sqrt(np.mean((y_t - y_p) ** 2)))

        # Epsilon-stabilized MAPE
        denom = np.where(np.abs(y_t) < 1.0, 1.0, np.abs(y_t))
        mape = float(np.mean(np.abs((y_t - y_p) / denom)) * 100.0)

        metrics: dict[str, float] = {
            "mae": round(mae, 3),
            "rmse": round(rmse, 3),
            "mape": round(mape, 2),
        }

        if lower_bound is not None and upper_bound is not None:
            l_b = np.asarray(lower_bound, dtype=float)
            u_b = np.asarray(upper_bound, dtype=float)
            in_interval = (y_t >= l_b) & (y_t <= u_b)
            coverage = float(np.mean(in_interval) * 100.0)
            metrics["interval_coverage_pct"] = round(coverage, 2)

        return metrics

    @staticmethod
    def evaluate_against_baselines(
        y_true: np.ndarray | pd.Series,
        y_ml_pred: np.ndarray | pd.Series,
        y_history: np.ndarray | pd.Series,
    ) -> dict[str, Any]:
        """
        Compare ML model predictions against:
        1. Persistence Baseline: y_hat = y_last
        2. Rolling Mean Baseline: y_hat = mean(y_last_4)
        """
        y_t = np.asarray(y_true, dtype=float)
        y_ml = np.asarray(y_ml_pred, dtype=float)
        y_hist = np.asarray(y_history, dtype=float)

        ml_metrics = ForecastEvaluator.calculate_metrics(y_t, y_ml)

        # Persistence baseline: constant value equal to last observed
        y_persistence = np.full_like(y_t, fill_value=y_hist[-1] if len(y_hist) > 0 else y_t[0])
        persistence_metrics = ForecastEvaluator.calculate_metrics(y_t, y_persistence)

        # Rolling mean baseline: mean of last 4 steps
        last_4_mean = float(np.mean(y_hist[-4:])) if len(y_hist) >= 4 else float(np.mean(y_hist))
        y_rolling = np.full_like(y_t, fill_value=last_4_mean)
        rolling_metrics = ForecastEvaluator.calculate_metrics(y_t, y_rolling)

        # Improvement relative to persistence MAE
        mae_improvement_pct = 0.0
        if persistence_metrics["mae"] > 0:
            mae_improvement_pct = (
                (persistence_metrics["mae"] - ml_metrics["mae"]) / persistence_metrics["mae"]
            ) * 100.0

        return {
            "ml_model": ml_metrics,
            "persistence_baseline": persistence_metrics,
            "rolling_mean_baseline": rolling_metrics,
            "mae_improvement_vs_persistence_pct": round(mae_improvement_pct, 2),
            "outperforms_persistence": ml_metrics["mae"] < persistence_metrics["mae"],
        }
