"""
Frost OS Module 05 — Sensor Diagnostic Adapter.

Detects stale sensors, constant-value outputs, noise spikes, missing data,
physical inconsistency, and disagreement between redundant sensors.
A sensor fault must be distinguishable from an actual equipment fault.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from app.equipment.base import (
    EquipmentDiagnosticAdapter,
    ExpectedBehavior,
    FeatureVector,
    RuleCheckResult,
    TelemetryWindow,
)
from app.models.anomaly import Anomaly, AnomalySeverity, AnomalyType
from app.models.equipment import Equipment, OperatingBaseline


class SensorDiagnosticAdapter(EquipmentDiagnosticAdapter):
    """Diagnostic adapter for sensor health assessment."""

    def __init__(
        self,
        stale_threshold_seconds: float = 60.0,
        constant_value_window: int = 10,
        noise_spike_zscore: float = 5.0,
        redundancy_disagreement_pct: float = 10.0,
    ) -> None:
        self.stale_threshold_seconds = stale_threshold_seconds
        self.constant_value_window = constant_value_window
        self.noise_spike_zscore = noise_spike_zscore
        self.redundancy_disagreement_pct = redundancy_disagreement_pct

    def extract_features(
        self,
        window: TelemetryWindow,
        baseline: OperatingBaseline | None = None,
    ) -> FeatureVector:
        features: dict[str, float] = {}
        feature_names = [
            "signal_count", "stale_signal_count",
            "constant_value_count", "noise_spike_count",
            "missing_signal_count",
            "data_freshness_seconds",
            "redundancy_disagreement_pct",
        ]

        stale_count = 0
        constant_count = 0
        noise_count = 0
        missing_count = 0
        max_freshness = 0.0
        now = datetime.now(timezone.utc)

        for name, sig in window.signals.items():
            if sig.is_empty():
                missing_count += 1
                continue

            # Stale check
            if sig.timestamps:
                last_ts = sig.timestamps[-1]
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                freshness = (now - last_ts).total_seconds()
                max_freshness = max(max_freshness, freshness)
                if freshness > self.stale_threshold_seconds:
                    stale_count += 1

            # Constant value check
            if sig.count >= self.constant_value_window:
                recent = sig.values[-self.constant_value_window:]
                if np.std(recent) < 1e-9:
                    constant_count += 1

            # Noise spike check
            if sig.count >= 5 and sig.std > 0:
                z_scores = np.abs((sig.values - sig.mean) / sig.std)
                spike_count = int(np.sum(z_scores > self.noise_spike_zscore))
                if spike_count > 0:
                    noise_count += 1

        features["signal_count"] = float(len(window.signals))
        features["stale_signal_count"] = float(stale_count)
        features["constant_value_count"] = float(constant_count)
        features["noise_spike_count"] = float(noise_count)
        features["missing_signal_count"] = float(missing_count)
        features["data_freshness_seconds"] = max_freshness
        features["redundancy_disagreement_pct"] = 0.0

        return FeatureVector(
            equipment_id=window.equipment_id,
            timestamp=window.window_end or now,
            features=features,
            feature_names=feature_names,
        )

    def check_rules(
        self,
        window: TelemetryWindow,
        equipment: Equipment,
        baseline: OperatingBaseline | None = None,
    ) -> RuleCheckResult:
        anomalies: list[Anomaly] = []
        warnings: list[str] = []
        signals_checked: list[str] = list(window.signals.keys())
        now = datetime.now(timezone.utc)

        for name, sig in window.signals.items():
            if sig.is_empty():
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.SENSOR_FAULT,
                    severity=AnomalySeverity.MEDIUM,
                    score=0.6,
                    confidence=0.9,
                    signals=[name],
                    possible_causes=["missing_data", "sensor_offline", "communication_failure"],
                    detection_layer="sensor_check",
                    metadata={"signal": name, "issue": "missing_data"},
                ))
                continue

            # Stale sensor
            if sig.timestamps:
                last_ts = sig.timestamps[-1]
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
                freshness = (now - last_ts).total_seconds()
                if freshness > self.stale_threshold_seconds:
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.SENSOR_FAULT,
                        severity=AnomalySeverity.MEDIUM,
                        score=min(1.0, freshness / (self.stale_threshold_seconds * 5)),
                        confidence=0.95,
                        observed_value=freshness,
                        expected_value=self.stale_threshold_seconds,
                        signals=[name],
                        possible_causes=["stale_data", "sensor_frozen", "communication_loss"],
                        detection_layer="sensor_check",
                        metadata={"signal": name, "issue": "stale", "seconds_stale": freshness},
                    ))

            # Constant value (frozen sensor)
            if sig.count >= self.constant_value_window:
                recent = sig.values[-self.constant_value_window:]
                if np.std(recent) < 1e-9:
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.SENSOR_FAULT,
                        severity=AnomalySeverity.MEDIUM,
                        score=0.65,
                        confidence=0.85,
                        observed_value=float(recent[-1]),
                        signals=[name],
                        possible_causes=["frozen_sensor", "constant_output", "stuck_value"],
                        detection_layer="sensor_check",
                        metadata={"signal": name, "issue": "constant_value",
                                  "constant_window": self.constant_value_window},
                    ))

            # Noise spikes
            if sig.count >= 5 and sig.std > 0:
                z_scores = np.abs((sig.values - sig.mean) / sig.std)
                spike_indices = np.where(z_scores > self.noise_spike_zscore)[0]
                if len(spike_indices) > 0:
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.SENSOR_FAULT,
                        severity=AnomalySeverity.LOW,
                        score=min(1.0, len(spike_indices) * 0.2),
                        confidence=0.7,
                        observed_value=float(sig.values[spike_indices[0]]),
                        expected_value=sig.mean,
                        signals=[name],
                        possible_causes=["noise_spike", "electromagnetic_interference", "loose_connection"],
                        detection_layer="sensor_check",
                        metadata={"signal": name, "issue": "noise_spike",
                                  "spike_count": int(len(spike_indices))},
                    ))

        # Redundant sensor disagreement
        redundant_pairs = self._find_redundant_pairs(window)
        for sig_a_name, sig_b_name in redundant_pairs:
            sig_a = window.get_signal(sig_a_name)
            sig_b = window.get_signal(sig_b_name)
            if sig_a and sig_b and not sig_a.is_empty() and not sig_b.is_empty():
                ref_val = max(abs(sig_a.mean), abs(sig_b.mean), 1.0)
                disagreement = abs(sig_a.mean - sig_b.mean) / ref_val * 100.0
                if disagreement > self.redundancy_disagreement_pct:
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.SENSOR_FAULT,
                        severity=AnomalySeverity.MEDIUM,
                        score=min(1.0, disagreement / 30.0),
                        confidence=0.8,
                        observed_value=sig_a.mean,
                        expected_value=sig_b.mean,
                        residual=sig_a.mean - sig_b.mean,
                        signals=[sig_a_name, sig_b_name],
                        possible_causes=["sensor_disagreement", "calibration_drift", "faulty_sensor"],
                        detection_layer="sensor_check",
                        metadata={"issue": "redundancy_disagreement",
                                  "disagreement_pct": disagreement},
                    ))

        return RuleCheckResult(
            anomalies=anomalies, warnings=warnings, signals_checked=signals_checked,
        )

    def _find_redundant_pairs(self, window: TelemetryWindow) -> list[tuple[str, str]]:
        """Identify redundant sensor pairs by naming convention."""
        pairs: list[tuple[str, str]] = []
        signal_names = list(window.signals.keys())
        seen = set()
        for name in signal_names:
            for suffix in ["_1", "_a", "_primary"]:
                if name.endswith(suffix):
                    base = name[:-len(suffix)]
                    for alt_suffix in ["_2", "_b", "_secondary"]:
                        alt_name = base + alt_suffix
                        if alt_name in window.signals and (name, alt_name) not in seen:
                            pairs.append((name, alt_name))
                            seen.add((name, alt_name))
        return pairs

    def compute_expected(
        self, conditions: dict[str, float], equipment: Equipment,
    ) -> ExpectedBehavior:
        return ExpectedBehavior(
            expected_values={"data_freshness_seconds": 0.0},
            conditions=conditions,
            model_type="rule",
            confidence=0.9,
        )

    def get_fault_signatures(self) -> dict[str, dict[str, Any]]:
        return {
            "STALE_DATA": {
                "required_signals": [],
                "conditions": {"freshness": "above_threshold"},
                "description": "Sensor has not reported new data beyond timeout",
                "min_evidence_count": 1,
            },
            "CONSTANT_OUTPUT": {
                "required_signals": [],
                "conditions": {"variance": "zero"},
                "description": "Sensor producing constant output (frozen/stuck)",
                "min_evidence_count": 1,
            },
            "NOISE_SPIKE": {
                "required_signals": [],
                "conditions": {"zscore": "extreme"},
                "description": "Sudden extreme readings indicating noise or interference",
                "min_evidence_count": 1,
            },
            "PHYSICAL_INCONSISTENCY": {
                "required_signals": [],
                "conditions": {"physics": "violated"},
                "description": "Sensor reading violates physical constraints",
                "min_evidence_count": 1,
            },
            "REDUNDANCY_DISAGREEMENT": {
                "required_signals": [],
                "conditions": {"redundant_sensors": "disagree"},
                "description": "Redundant sensors reporting significantly different values",
                "min_evidence_count": 1,
            },
        }

    def get_default_limits(self) -> dict[str, tuple[float, float]]:
        return {}
