"""
Frost OS Module 04 — Station Load Model Training Pipeline.

Trains Gradient Boosting models for station energy demand using heating sensitivities,
cyclical time features, and active mission profiles.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import structlog
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

logger = structlog.get_logger(__name__)

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False


class LoadModelTrainer:
    """Trains Gradient Boosting demand forecasting models."""

    @staticmethod
    def train_load_model(
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
    ) -> Any:
        """Fit XGBoost model for station demand."""
        if not HAS_XGB:
            logger.warning("xgboost_not_installed_skipping_fit")
            return None

        model = xgb.XGBRegressor(
            n_estimators=70,
            max_depth=4,
            learning_rate=0.07,
            subsample=0.85,
            random_state=42,
        )
        model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        val_preds = model.predict(X_val)
        mae = mean_absolute_error(y_val, val_preds)
        rmse = root_mean_squared_error(y_val, val_preds)
        logger.info("load_model_trained", val_mae=round(float(mae), 3), val_rmse=round(float(rmse), 3))
        return model
