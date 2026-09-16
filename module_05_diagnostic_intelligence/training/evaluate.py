"""
Frost OS Module 05 — Model Evaluation.

Evaluates trained models against test datasets with metrics
reporting and visualization.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    precision_recall_fscore_support,
)

logger = structlog.get_logger(__name__)


def evaluate_anomaly_detector(
    model: Any,
    scaler: Any,
    normal_features: np.ndarray,
    anomaly_features: np.ndarray | None = None,
) -> dict[str, Any]:
    """
    Evaluate anomaly detection model.

    Tests false positive rate on normal data and detection rate on anomalies.
    """
    # Normal data — should be predicted as inliers (1)
    normal_scaled = scaler.transform(normal_features)
    normal_preds = model.predict(normal_scaled)
    false_positives = int(np.sum(normal_preds == -1))
    fpr = false_positives / len(normal_preds)

    result = {
        "normal_samples": len(normal_features),
        "false_positives": false_positives,
        "false_positive_rate": round(fpr, 4),
    }

    if anomaly_features is not None and len(anomaly_features) > 0:
        anomaly_scaled = scaler.transform(anomaly_features)
        anomaly_preds = model.predict(anomaly_scaled)
        true_positives = int(np.sum(anomaly_preds == -1))
        tpr = true_positives / len(anomaly_preds) if len(anomaly_preds) > 0 else 0.0

        result.update({
            "anomaly_samples": len(anomaly_features),
            "true_positives": true_positives,
            "detection_rate": round(tpr, 4),
        })

    return result


def evaluate_fault_classifier(
    model: Any,
    scaler: Any,
    features: np.ndarray,
    labels: np.ndarray,
    label_names: dict[int, str],
) -> dict[str, Any]:
    """Evaluate fault classification model."""
    features_scaled = scaler.transform(features)
    predictions = model.predict(features_scaled)

    accuracy = accuracy_score(labels, predictions)
    precision, recall, f1, support = precision_recall_fscore_support(
        labels, predictions, average="weighted",
    )

    cm = confusion_matrix(labels, predictions)

    report = classification_report(
        labels, predictions,
        target_names=[label_names.get(i, str(i)) for i in sorted(label_names.keys())],
        output_dict=True,
    )

    return {
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "confusion_matrix": cm.tolist(),
        "classification_report": report,
    }


if __name__ == "__main__":
    import joblib
    from training.dataset_builder import build_wind_turbine_dataset

    print("Evaluating wind turbine models...")

    data = build_wind_turbine_dataset(num_normal=200, num_icing=50, num_bearing=50)

    # Evaluate isolation forest
    try:
        artifact = joblib.load("models/wind_isolation_forest.joblib")
        normal_mask = data["labels"] == 0
        anomaly_mask = data["labels"] != 0
        result = evaluate_anomaly_detector(
            artifact["model"],
            artifact["scaler"],
            data["features"][normal_mask],
            data["features"][anomaly_mask],
        )
        print(f"\nIsolation Forest: {result}")
    except FileNotFoundError:
        print("No trained Isolation Forest model found. Run train_models.py first.")

    # Evaluate fault classifier
    try:
        artifact = joblib.load("models/wind_fault_classifier.joblib")
        result = evaluate_fault_classifier(
            artifact["model"],
            artifact["scaler"],
            data["features"],
            data["labels"],
            data["label_names"],
        )
        print(f"\nFault Classifier: accuracy={result['accuracy']}, f1={result['f1_score']}")
    except FileNotFoundError:
        print("No trained fault classifier found. Run train_models.py first.")
