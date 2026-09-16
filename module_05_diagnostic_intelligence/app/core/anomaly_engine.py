"""
Frost OS Module 05 — Anomaly Engine.

Implements 5-layer anomaly detection:
1. Deterministic limit checks
2. Rate-of-change checks
3. Residual actual-vs-expected checks
4. Statistical detection (z-score, IQR, EWMA)
5. ML anomaly detection (Isolation Forest)

Rules and physics always take precedence. ML confirms but does not
override deterministic detections. Avoids ML-only diagnosis.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog

from app.config.settings import Settings
from app.core.baseline_engine import BaselineEngine
from app.equipment.base import FeatureVector, TelemetryWindow
from app.models.anomaly import Anomaly, AnomalySeverity, AnomalyType
from app.models.equipment import Equipment

logger = structlog.get_logger(__name__)


def _severity_from_score(score: float) -> AnomalySeverity:
    """Map anomaly score to severity level."""
    if score >= 0.8:
        return AnomalySeverity.CRITICAL
    if score >= 0.6:
        return AnomalySeverity.HIGH
    if score >= 0.4:
        return AnomalySeverity.MEDIUM
    if score >= 0.2:
        return AnomalySeverity.LOW
    return AnomalySeverity.INFO


class AnomalyEngine:
    """
    5-layer anomaly detection engine.

    Layers are applied sequentially. Deterministic checks (layers 1-2) have
    highest authority. Statistical (layer 4) and ML (layer 5) supplement
    but never override rule-based detections.
    """

    def __init__(
        self,
        settings: Settings,
        baseline_engine: BaselineEngine | None = None,
    ) -> None:
        self.settings = settings
        self.baseline_engine = baseline_engine
        self._isolation_forest = None
        self._ewma_state: dict[str, dict[str, float]] = {}

    def detect_anomalies(
        self,
        window: TelemetryWindow,
        equipment: Equipment,
        features: FeatureVector | None = None,
        rule_anomalies: list[Anomaly] | None = None,
    ) -> list[Anomaly]:
        """
        Run all 5 anomaly detection layers and merge results.

        Returns deduplicated anomalies sorted by severity (highest first).
        """
        all_anomalies: list[Anomaly] = []

        # Layer 1: Deterministic limit checks
        limit_anomalies = self._layer1_limit_checks(window, equipment)
        all_anomalies.extend(limit_anomalies)

        # Layer 2: Rate-of-change checks
        roc_anomalies = self._layer2_rate_of_change(window, equipment)
        all_anomalies.extend(roc_anomalies)

        # Layer 3: Residual actual-vs-expected
        residual_anomalies = self._layer3_residual_checks(window, equipment)
        all_anomalies.extend(residual_anomalies)

        # Layer 4: Statistical detection
        stat_anomalies = self._layer4_statistical(window, equipment)
        all_anomalies.extend(stat_anomalies)

        # Layer 5: ML detection (only if sufficient data)
        if features is not None:
            ml_anomalies = self._layer5_ml_detection(features, equipment)
            all_anomalies.extend(ml_anomalies)

        # Include rule-check anomalies from equipment adapter
        if rule_anomalies:
            all_anomalies.extend(rule_anomalies)

        # Deduplicate and sort by severity
        merged = self._merge_anomalies(all_anomalies)
        return sorted(merged, key=lambda a: self._severity_rank(a.severity), reverse=True)

    def _layer1_limit_checks(
        self,
        window: TelemetryWindow,
        equipment: Equipment,
    ) -> list[Anomaly]:
        """Layer 1: Hard physical limit violations."""
        from app.core.telemetry_processor import METRIC_LIMITS

        anomalies: list[Anomaly] = []
        now = datetime.now(timezone.utc)

        for sig_name, sig_data in window.signals.items():
            if sig_data.is_empty():
                continue

            limits = METRIC_LIMITS.get(sig_name)
            if limits is None:
                continue

            latest = sig_data.latest
            if latest < limits[0] or latest > limits[1]:
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.LIMIT_VIOLATION,
                    severity=AnomalySeverity.HIGH,
                    score=0.85,
                    confidence=0.95,
                    observed_value=latest,
                    expected_value=(limits[0] + limits[1]) / 2,
                    residual=latest - limits[1] if latest > limits[1] else latest - limits[0],
                    signals=[sig_name],
                    possible_causes=["physical_limit_violation", "sensor_error"],
                    detection_layer="layer1_limit",
                ))

        return anomalies

    def _layer2_rate_of_change(
        self,
        window: TelemetryWindow,
        equipment: Equipment,
    ) -> list[Anomaly]:
        """Layer 2: Implausible rate-of-change detection."""
        anomalies: list[Anomaly] = []
        now = datetime.now(timezone.utc)

        for sig_name, sig_data in window.signals.items():
            if sig_data.count < 2:
                continue

            # Compute diff per time step
            diffs = np.abs(np.diff(sig_data.values))
            max_diff = float(np.max(diffs)) if len(diffs) > 0 else 0.0

            if max_diff > self.settings.max_rate_of_change_per_second:
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.RATE_OF_CHANGE,
                    severity=AnomalySeverity.MEDIUM,
                    score=min(1.0, max_diff / (self.settings.max_rate_of_change_per_second * 3)),
                    confidence=0.7,
                    observed_value=max_diff,
                    expected_value=self.settings.max_rate_of_change_per_second,
                    signals=[sig_name],
                    possible_causes=["rapid_change", "sensor_glitch", "sudden_event"],
                    detection_layer="layer2_roc",
                ))

        return anomalies

    def _layer3_residual_checks(
        self,
        window: TelemetryWindow,
        equipment: Equipment,
    ) -> list[Anomaly]:
        """Layer 3: Actual vs expected residual checks using baselines."""
        anomalies: list[Anomaly] = []
        now = datetime.now(timezone.utc)

        if self.baseline_engine is None:
            return anomalies

        for sig_name, sig_data in window.signals.items():
            if sig_data.is_empty():
                continue

            result = self.baseline_engine.compute_residual(
                equipment_id=window.equipment_id,
                metric_name=sig_name,
                observed_value=sig_data.mean,
            )
            if result is None:
                continue

            residual_pct = abs(result["residual_pct"])
            threshold_pct = self.settings.residual_deviation_threshold * 100.0

            if residual_pct > threshold_pct:
                score = min(1.0, residual_pct / (threshold_pct * 3))
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.RESIDUAL_DEVIATION,
                    severity=_severity_from_score(score),
                    score=score,
                    confidence=0.65,
                    observed_value=sig_data.mean,
                    expected_value=result["expected_mean"],
                    residual=result["residual"],
                    signals=[sig_name],
                    possible_causes=["equipment_deviation", "operating_condition_change"],
                    detection_layer="layer3_residual",
                ))

        return anomalies

    def _layer4_statistical(
        self,
        window: TelemetryWindow,
        equipment: Equipment,
    ) -> list[Anomaly]:
        """Layer 4: Statistical detection — z-score, IQR, EWMA."""
        anomalies: list[Anomaly] = []
        now = datetime.now(timezone.utc)

        for sig_name, sig_data in window.signals.items():
            if sig_data.count < 5:
                continue

            values = sig_data.values[~np.isnan(sig_data.values)]
            if len(values) < 5:
                continue

            # Z-score check on latest value
            mean = float(np.mean(values))
            std = float(np.std(values))
            if std > 1e-9:
                z = abs((sig_data.latest - mean) / std)
                if z > self.settings.anomaly_zscore_threshold:
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.STATISTICAL,
                        severity=_severity_from_score(min(1.0, z / 6.0)),
                        score=min(1.0, z / 6.0),
                        confidence=0.6,
                        observed_value=sig_data.latest,
                        expected_value=mean,
                        residual=sig_data.latest - mean,
                        signals=[sig_name],
                        possible_causes=["statistical_outlier"],
                        detection_layer="layer4_zscore",
                        metadata={"zscore": z},
                    ))

            # IQR check
            q1 = float(np.percentile(values, 25))
            q3 = float(np.percentile(values, 75))
            iqr = q3 - q1
            if iqr > 1e-9:
                lower = q1 - self.settings.anomaly_iqr_multiplier * iqr
                upper = q3 + self.settings.anomaly_iqr_multiplier * iqr
                if sig_data.latest < lower or sig_data.latest > upper:
                    deviation = max(lower - sig_data.latest, sig_data.latest - upper, 0)
                    norm_dev = deviation / iqr if iqr > 0 else 0
                    # Only add if not already caught by z-score
                    if not any(a.detection_layer == "layer4_zscore" and sig_name in a.signals
                              for a in anomalies):
                        anomalies.append(Anomaly(
                            equipment_id=window.equipment_id,
                            station_id=window.station_id,
                            timestamp=now,
                            type=AnomalyType.STATISTICAL,
                            severity=_severity_from_score(min(1.0, norm_dev / 3.0)),
                            score=min(1.0, norm_dev / 3.0),
                            confidence=0.55,
                            observed_value=sig_data.latest,
                            signals=[sig_name],
                            possible_causes=["iqr_outlier"],
                            detection_layer="layer4_iqr",
                            metadata={"iqr": iqr, "lower_fence": lower, "upper_fence": upper},
                        ))

            # EWMA tracking
            ewma_key = f"{window.equipment_id}:{sig_name}"
            alpha = self.settings.ewma_alpha
            if ewma_key not in self._ewma_state:
                self._ewma_state[ewma_key] = {"ewma": sig_data.latest, "ewma_var": 0.0}

            state = self._ewma_state[ewma_key]
            prev_ewma = state["ewma"]
            new_ewma = alpha * sig_data.latest + (1 - alpha) * prev_ewma
            ewma_residual = abs(sig_data.latest - new_ewma)
            state["ewma"] = new_ewma
            state["ewma_var"] = alpha * ewma_residual ** 2 + (1 - alpha) * state["ewma_var"]
            ewma_std = max(state["ewma_var"] ** 0.5, 1e-9)

            if ewma_residual > 3 * ewma_std and ewma_std > 1e-6:
                if not any(sig_name in a.signals and a.detection_layer.startswith("layer4")
                           for a in anomalies):
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.STATISTICAL,
                        severity=AnomalySeverity.LOW,
                        score=min(1.0, ewma_residual / (6 * ewma_std)),
                        confidence=0.5,
                        observed_value=sig_data.latest,
                        expected_value=new_ewma,
                        residual=sig_data.latest - new_ewma,
                        signals=[sig_name],
                        possible_causes=["ewma_deviation", "trend_shift"],
                        detection_layer="layer4_ewma",
                    ))

        return anomalies

    def _layer5_ml_detection(
        self,
        features: FeatureVector,
        equipment: Equipment,
    ) -> list[Anomaly]:
        """
        Layer 5: ML anomaly detection using Isolation Forest.

        Only activated when sufficient data exists (min_samples_for_ml).
        ML results supplement but do not override rule-based detections.
        """
        anomalies: list[Anomaly] = []
        now = datetime.now(timezone.utc)

        if self._isolation_forest is None:
            return anomalies

        try:
            feature_array = features.to_array().reshape(1, -1)
            # Replace NaN with 0 for ML
            feature_array = np.nan_to_num(feature_array, nan=0.0)

            prediction = self._isolation_forest.predict(feature_array)
            score = self._isolation_forest.decision_function(feature_array)

            if prediction[0] == -1:  # Anomaly detected
                anomaly_score = min(1.0, max(0.0, -float(score[0])))
                anomalies.append(Anomaly(
                    equipment_id=features.equipment_id,
                    station_id=equipment.station_id,
                    timestamp=now,
                    type=AnomalyType.ML_DETECTED,
                    severity=_severity_from_score(anomaly_score),
                    score=anomaly_score,
                    confidence=0.5,  # ML confidence is lower
                    signals=features.feature_names,
                    possible_causes=["ml_detected_pattern_anomaly"],
                    detection_layer="layer5_isolation_forest",
                    metadata={
                        "model_type": "IsolationForest",
                        "raw_score": float(score[0]),
                    },
                ))
        except Exception as e:
            logger.warning("ml_anomaly_detection_error", error=str(e))

        return anomalies

    def set_isolation_forest(self, model: Any) -> None:
        """Set a trained Isolation Forest model for layer 5 detection."""
        self._isolation_forest = model

    def _merge_anomalies(self, anomalies: list[Anomaly]) -> list[Anomaly]:
        """Deduplicate anomalies that flag the same signal with the same type."""
        seen: dict[str, Anomaly] = {}
        for a in anomalies:
            key = f"{a.equipment_id}:{','.join(sorted(a.signals))}:{a.type.value}"
            if key not in seen or self._severity_rank(a.severity) > self._severity_rank(seen[key].severity):
                seen[key] = a
        return list(seen.values())

    @staticmethod
    def _severity_rank(severity: AnomalySeverity) -> int:
        ranking = {
            AnomalySeverity.INFO: 0,
            AnomalySeverity.LOW: 1,
            AnomalySeverity.MEDIUM: 2,
            AnomalySeverity.HIGH: 3,
            AnomalySeverity.CRITICAL: 4,
        }
        return ranking.get(severity, 0)
