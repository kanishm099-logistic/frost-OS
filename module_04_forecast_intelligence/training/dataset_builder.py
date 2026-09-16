"""
Frost OS Module 04 — Chronological Dataset Builder.

Constructs training, validation, and test datasets with strict temporal ordering.
NEVER performs random shuffling across time to prevent forward-looking data leakage.
"""

from __future__ import annotations

import pandas as pd


class TimeSeriesDatasetBuilder:
    """Builds strictly ordered chronological splits for time series forecasting."""

    @staticmethod
    def train_val_test_split(
        df: pd.DataFrame,
        train_ratio: float = 0.70,
        val_ratio: float = 0.15,
        test_ratio: float = 0.15,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Partition dataframe chronologically into [Train, Validation, Test].
        Validates that train_ratio + val_ratio + test_ratio == 1.0.
        """
        assert abs((train_ratio + val_ratio + test_ratio) - 1.0) < 1e-5, "Ratios must sum to 1.0"
        n = len(df)
        if n < 10:
            raise ValueError(f"Insufficient samples ({n}) for time-series splitting")

        train_end = int(n * train_ratio)
        val_end = int(n * (train_ratio + val_ratio))

        train_df = df.iloc[:train_end].copy()
        val_df = df.iloc[train_end:val_end].copy()
        test_df = df.iloc[val_end:].copy()

        # Strict temporal monotonicity verification
        if "timestamp" in df.columns:
            assert train_df["timestamp"].max() <= val_df["timestamp"].min(), "Train/Val temporal overlap"
            assert val_df["timestamp"].max() <= test_df["timestamp"].min(), "Val/Test temporal overlap"

        return train_df, val_df, test_df

    @staticmethod
    def extract_feature_matrix(
        df: pd.DataFrame,
        feature_cols: list[str],
        target_col: str,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Extract clean feature matrix X and target vector y."""
        missing = [c for c in feature_cols if c not in df.columns]
        if missing:
            raise KeyError(f"Missing required feature columns in dataframe: {missing}")
        if target_col not in df.columns:
            raise KeyError(f"Missing target column: {target_col}")

        X = df[feature_cols].copy()
        y = df[target_col].copy()
        return X, y
