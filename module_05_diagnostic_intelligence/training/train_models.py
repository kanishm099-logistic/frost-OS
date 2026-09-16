"""
Frost OS Module 05 — Model Training Pipeline.

Trains Isolation Forest (anomaly detection) and XGBoost (fault classification)
models from labeled datasets. Models are saved with metadata for registry.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import joblib
import numpy as np
import structlog
from sklearn.ensemble import IsolationForest
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

logger = structlog.get_logger(__name__)


def train_isolation_forest(
    features: np.ndarray,
    contamination: float = 0.05,
    random_state: int = 42,
    model_path: str = "models/isolation_forest.joblib",
) -> dict[str, Any]:
    """
    Train an Isolation Forest for anomaly detection.

    Uses only 'normal' labeled data for unsupervised training.
    """
    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features)

    model = IsolationForest(
        contamination=contamination,
        random_state=random_state,
        n_estimators=200,
        max_samples="auto",
    )
    model.fit(features_scaled)

    # Save model and scaler
    os.makedirs(os.path.dirname(model_path) or "models", exist_ok=True)
    artifact = {
        "model": model,
        "scaler": scaler,
        "training_date": datetime.now(timezone.utc).isoformat(),
        "feature_count": features.shape[1],
        "training_samples": features.shape[0],
        "contamination": contamination,
    }
    joblib.dump(artifact, model_path)

    # Evaluate on training data
    predictions = model.predict(features_scaled)
    scores = model.decision_function(features_scaled)
    anomaly_count = int(np.sum(predictions == -1))

    logger.info(
        "isolation_forest_trained",
        samples=features.shape[0],
        features=features.shape[1],
        anomalies_detected=anomaly_count,
        model_path=model_path,
    )

    return {
        "model_path": model_path,
        "training_samples": features.shape[0],
        "anomalies_detected": anomaly_count,
        "mean_score": float(np.mean(scores)),
        "std_score": float(np.std(scores)),
    }


def train_fault_classifier(
    features: np.ndarray,
    labels: np.ndarray,
    label_names: dict[int, str],
    model_path: str = "models/fault_classifier.joblib",
    random_state: int = 42,
) -> dict[str, Any]:
    """
    Train an XGBoost classifier for fault classification.

    Trained on labeled data with known fault types.
    """
    try:
        from xgboost import XGBClassifier
    except ImportError:
        logger.warning("xgboost_not_available, skipping fault classifier training")
        return {"error": "XGBoost not installed"}

    scaler = StandardScaler()
    features_scaled = scaler.fit_transform(features)

    X_train, X_test, y_train, y_test = train_test_split(
        features_scaled, labels, test_size=0.2, random_state=random_state,
        stratify=labels,
    )

    model = XGBClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.1,
        random_state=random_state,
        use_label_encoder=False,
        eval_metric="mlogloss",
    )
    model.fit(X_train, y_train)

    # Evaluate
    train_acc = float(model.score(X_train, y_train))
    test_acc = float(model.score(X_test, y_test))

    os.makedirs(os.path.dirname(model_path) or "models", exist_ok=True)
    artifact = {
        "model": model,
        "scaler": scaler,
        "label_names": label_names,
        "training_date": datetime.now(timezone.utc).isoformat(),
        "feature_count": features.shape[1],
    }
    joblib.dump(artifact, model_path)

    logger.info(
        "fault_classifier_trained",
        train_accuracy=train_acc,
        test_accuracy=test_acc,
        classes=len(label_names),
        model_path=model_path,
    )

    return {
        "model_path": model_path,
        "train_accuracy": round(train_acc, 4),
        "test_accuracy": round(test_acc, 4),
        "training_samples": len(y_train),
        "test_samples": len(y_test),
        "classes": label_names,
    }


if __name__ == "__main__":
    from training.dataset_builder import build_wind_turbine_dataset, build_battery_dataset

    print("=" * 60)
    print("Frost OS Module 05 — Model Training Pipeline")
    print("=" * 60)

    # Wind turbine
    print("\n[1] Building wind turbine dataset...")
    wind_data = build_wind_turbine_dataset()

    print("[2] Training Isolation Forest (wind)...")
    normal_mask = wind_data["labels"] == 0
    if_result = train_isolation_forest(
        wind_data["features"][normal_mask],
        model_path="models/wind_isolation_forest.joblib",
    )
    print(f"    Result: {if_result}")

    print("[3] Training fault classifier (wind)...")
    fc_result = train_fault_classifier(
        wind_data["features"],
        wind_data["labels"],
        wind_data["label_names"],
        model_path="models/wind_fault_classifier.joblib",
    )
    print(f"    Result: {fc_result}")

    # Battery
    print("\n[4] Building battery dataset...")
    bat_data = build_battery_dataset()

    print("[5] Training Isolation Forest (battery)...")
    normal_mask = bat_data["labels"] == 0
    if_result = train_isolation_forest(
        bat_data["features"][normal_mask],
        model_path="models/battery_isolation_forest.joblib",
    )
    print(f"    Result: {if_result}")

    print("\n✓ Training pipeline complete")
