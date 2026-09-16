"""
Frost OS Module 04 — Model Registry & Baseline Evaluation Tests.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.model_manager import ModelManager
from app.models.forecast import ForecastTarget
from training.dataset_builder import TimeSeriesDatasetBuilder
from training.evaluate import ForecastEvaluator


def test_model_registry_management():
    """Verify ModelManager lists default models and updates metrics."""
    mgr = ModelManager()
    models = mgr.list_models()
    assert len(models) >= 3

    model_names = [m.model_name for m in models]
    assert "solar_pv_v0.1" in model_names
    assert "wind_v0.1" in model_names
    assert "load_v0.1" in model_names

    # Update metrics
    mgr.update_metrics("solar_pv_v0.1", {"mae": 2.1, "rmse": 3.4})
    solar = mgr.get_model("solar_pv_v0.1")
    assert solar is not None
    assert solar.metrics["mae"] == 2.1


def test_time_series_chronological_splitting():
    """Verify splitting preserves strict temporal order and rejects random shuffling."""
    dates = pd.date_range("2026-01-01", periods=100, freq="15min")
    df = pd.DataFrame({
        "timestamp": dates,
        "feature1": np.random.randn(100),
        "target": np.random.randn(100),
    })

    train_df, val_df, test_df = TimeSeriesDatasetBuilder.train_val_test_split(
        df, train_ratio=0.7, val_ratio=0.15, test_ratio=0.15
    )

    assert len(train_df) == 70
    assert len(val_df) == 15
    assert len(test_df) == 15

    assert train_df["timestamp"].max() <= val_df["timestamp"].min()
    assert val_df["timestamp"].max() <= test_df["timestamp"].min()


def test_evaluation_metrics_and_persistence_baseline():
    """Verify MAE/RMSE/MAPE calculations and comparison against persistence baseline."""
    y_true = np.array([10.0, 12.0, 15.0, 18.0, 22.0, 25.0])
    # Accurate ML prediction
    y_ml = np.array([10.5, 12.2, 14.8, 17.9, 21.8, 25.2])
    lower = y_ml - 2.0
    upper = y_ml + 2.0
    y_history = np.array([8.0, 9.0, 9.5, 10.0])

    eval_result = ForecastEvaluator.evaluate_against_baselines(
        y_true=y_true,
        y_ml_pred=y_ml,
        y_history=y_history,
    )

    assert "ml_model" in eval_result
    assert "persistence_baseline" in eval_result
    assert eval_result["ml_model"]["mae"] < eval_result["persistence_baseline"]["mae"]
    assert eval_result["outperforms_persistence"] is True

    # Interval coverage test
    metrics = ForecastEvaluator.calculate_metrics(y_true, y_ml, lower, upper)
    assert metrics["interval_coverage_pct"] == 100.0
