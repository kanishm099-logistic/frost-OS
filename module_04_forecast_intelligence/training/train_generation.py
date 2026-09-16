"""
Frost OS Module 04 — Renewable Generation Model Training Pipeline.

Trains XGBoost residual correction models for:
1. Solar PV: residual on top of clear-sky physical baseline
2. Wind Turbine: residual on top of cold-air aerodynamic power curve
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import structlog
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

logger = structlog.get_logger(__name__)

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False


class GenerationModelTrainer:
    """Trains physical+ML hybrid models for solar and wind generation."""

    @staticmethod
    def train_solar_residual_model(
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
    ) -> Any:
        """Fit XGBoost model predicting solar generation."""
        if not HAS_XGB:
            logger.warning("xgboost_not_installed_skipping_fit")
            return None

        model = xgb.XGBRegressor(
            n_estimators=60,
            max_depth=4,
            learning_rate=0.08,
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
        logger.info("solar_model_trained", val_mae=round(float(mae), 3), val_rmse=round(float(rmse), 3))
        return model

    @staticmethod
    def train_wind_residual_model(
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
    ) -> Any:
        """Fit XGBoost model predicting wind turbine generation."""
        if not HAS_XGB:
            logger.warning("xgboost_not_installed_skipping_fit")
            return None

        model = xgb.XGBRegressor(
            n_estimators=80,
            max_depth=5,
            learning_rate=0.06,
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
        logger.info("wind_model_trained", val_mae=round(float(mae), 3), val_rmse=round(float(rmse), 3))
        return model
