"""
Frost OS Module 05 — Hydrogen System Diagnostic Adapter.

Monitors tank level, pressure, temperature, flow rate, electrolyzer/fuel-cell
output and efficiency. Never directly commands hydrogen equipment.
"""

from __future__ import annotations

from datetime import datetime, timezone
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


class HydrogenSystemAdapter(EquipmentDiagnosticAdapter):
    """Diagnostic adapter for hydrogen storage, electrolyzer, and fuel cell systems."""

    def __init__(
        self,
        max_pressure_bar: float = 700.0,
        min_pressure_bar: float = 5.0,
        max_temperature_c: float = 85.0,
        nominal_fc_efficiency: float = 0.55,
        nominal_ely_efficiency: float = 0.65,
        pressure_rate_threshold_bar_per_min: float = 5.0,
    ) -> None:
        self.max_pressure_bar = max_pressure_bar
        self.min_pressure_bar = min_pressure_bar
        self.max_temperature_c = max_temperature_c
        self.nominal_fc_efficiency = nominal_fc_efficiency
        self.nominal_ely_efficiency = nominal_ely_efficiency
        self.pressure_rate_threshold = pressure_rate_threshold_bar_per_min

    def extract_features(
        self,
        window: TelemetryWindow,
        baseline: OperatingBaseline | None = None,
    ) -> FeatureVector:
        features: dict[str, float] = {}
        feature_names = [
            "pressure_bar_mean", "pressure_bar_rate",
            "temperature_c_mean", "temperature_c_max",
            "hydrogen_level_pct", "level_rate",
            "flow_rate_mean",
            "fc_power_kw", "ely_power_kw",
            "fc_efficiency", "ely_efficiency",
        ]

        # Pressure
        p_sig = window.get_signal("pressure_bar")
        if p_sig and not p_sig.is_empty():
            features["pressure_bar_mean"] = p_sig.mean
            if p_sig.count >= 2:
                features["pressure_bar_rate"] = float(p_sig.values[-1] - p_sig.values[0])
            else:
                features["pressure_bar_rate"] = 0.0
        else:
            features["pressure_bar_mean"] = 350.0
            features["pressure_bar_rate"] = 0.0

        # Temperature
        t_sig = window.get_signal("temperature_c")
        features["temperature_c_mean"] = t_sig.mean if t_sig and not t_sig.is_empty() else 25.0
        features["temperature_c_max"] = (
            float(np.nanmax(t_sig.values)) if t_sig and not t_sig.is_empty() else 25.0
        )

        # Level
        lvl_sig = window.get_signal("hydrogen_level_pct")
        if lvl_sig and not lvl_sig.is_empty():
            features["hydrogen_level_pct"] = lvl_sig.latest
            if lvl_sig.count >= 2:
                features["level_rate"] = float(lvl_sig.values[-1] - lvl_sig.values[0])
            else:
                features["level_rate"] = 0.0
        else:
            features["hydrogen_level_pct"] = 50.0
            features["level_rate"] = 0.0

        # Flow
        flow_sig = window.get_signal("flow_rate")
        features["flow_rate_mean"] = flow_sig.mean if flow_sig and not flow_sig.is_empty() else 0.0

        # Power
        fc_sig = window.get_signal("fc_power_kw")
        ely_sig = window.get_signal("ely_power_kw")
        features["fc_power_kw"] = fc_sig.latest if fc_sig and not fc_sig.is_empty() else 0.0
        features["ely_power_kw"] = ely_sig.latest if ely_sig and not ely_sig.is_empty() else 0.0

        # Efficiency
        features["fc_efficiency"] = self.nominal_fc_efficiency
        features["ely_efficiency"] = self.nominal_ely_efficiency

        return FeatureVector(
            equipment_id=window.equipment_id,
            timestamp=window.window_end or datetime.now(timezone.utc),
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
        signals_checked: list[str] = []
        now = datetime.now(timezone.utc)

        # Pressure limits
        if window.has_signal("pressure_bar"):
            signals_checked.append("pressure_bar")
            p_sig = window.get_signal("pressure_bar")

            if p_sig.latest > self.max_pressure_bar:
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.LIMIT_VIOLATION,
                    severity=AnomalySeverity.CRITICAL,
                    score=0.95,
                    confidence=0.9,
                    observed_value=p_sig.latest,
                    expected_value=self.max_pressure_bar,
                    residual=p_sig.latest - self.max_pressure_bar,
                    signals=["pressure_bar"],
                    possible_causes=["overpressure", "relief_valve_failure", "sensor_error"],
                    detection_layer="rule_check",
                ))
            elif p_sig.latest < self.min_pressure_bar:
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.LIMIT_VIOLATION,
                    severity=AnomalySeverity.HIGH,
                    score=0.8,
                    confidence=0.85,
                    observed_value=p_sig.latest,
                    expected_value=self.min_pressure_bar,
                    residual=p_sig.latest - self.min_pressure_bar,
                    signals=["pressure_bar"],
                    possible_causes=["leak", "consumption_exceeded", "sensor_error"],
                    detection_layer="rule_check",
                ))

            # Pressure rate of change
            if p_sig.count >= 2:
                rate = abs(float(p_sig.values[-1] - p_sig.values[0]))
                if rate > self.pressure_rate_threshold:
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.RATE_OF_CHANGE,
                        severity=AnomalySeverity.HIGH,
                        score=0.75,
                        confidence=0.8,
                        observed_value=rate,
                        expected_value=self.pressure_rate_threshold,
                        signals=["pressure_bar"],
                        possible_causes=["rapid_depressurization", "leak", "valve_issue"],
                        detection_layer="rule_check",
                    ))

        # Temperature check
        if window.has_signal("temperature_c"):
            signals_checked.append("temperature_c")
            t_sig = window.get_signal("temperature_c")
            if t_sig.latest > self.max_temperature_c:
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.LIMIT_VIOLATION,
                    severity=AnomalySeverity.HIGH,
                    score=0.8,
                    confidence=0.85,
                    observed_value=t_sig.latest,
                    expected_value=self.max_temperature_c,
                    signals=["temperature_c"],
                    possible_causes=["overheating", "cooling_failure", "high_conversion_load"],
                    detection_layer="rule_check",
                ))

        # Unexpected level drop
        if window.has_signal("hydrogen_level_pct"):
            signals_checked.append("hydrogen_level_pct")
            lvl_sig = window.get_signal("hydrogen_level_pct")
            if lvl_sig.count >= 2:
                drop = float(lvl_sig.values[0] - lvl_sig.values[-1])
                fc_sig = window.get_signal("fc_power_kw")
                fc_running = fc_sig and not fc_sig.is_empty() and fc_sig.mean > 1.0
                if drop > 5.0 and not fc_running:
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.RESIDUAL_DEVIATION,
                        severity=AnomalySeverity.HIGH,
                        score=0.7,
                        confidence=0.7,
                        observed_value=drop,
                        expected_value=0.0,
                        signals=["hydrogen_level_pct"],
                        possible_causes=["leak", "unmetered_consumption", "sensor_drift"],
                        detection_layer="rule_check",
                    ))

        return RuleCheckResult(
            anomalies=anomalies,
            warnings=warnings,
            signals_checked=signals_checked,
        )

    def compute_expected(
        self, conditions: dict[str, float], equipment: Equipment,
    ) -> ExpectedBehavior:
        return ExpectedBehavior(
            expected_values={
                "pressure_bar": conditions.get("pressure_bar", 350.0),
                "temperature_c": 25.0,
            },
            conditions=conditions,
            model_type="physics",
            confidence=0.7,
        )

    def get_fault_signatures(self) -> dict[str, dict[str, Any]]:
        return {
            "PRESSURE_ANOMALY": {
                "required_signals": ["pressure_bar"],
                "conditions": {"pressure": "out_of_range_or_rapid_change"},
                "description": "Abnormal tank pressure behavior",
                "min_evidence_count": 1,
            },
            "LEAK_INDICATOR": {
                "required_signals": ["hydrogen_level_pct"],
                "optional_signals": ["pressure_bar", "flow_rate"],
                "conditions": {"level_drop": "unexplained"},
                "description": "Hydrogen level dropping without fuel cell operation",
                "min_evidence_count": 2,
            },
            "EFFICIENCY_DEGRADATION": {
                "required_signals": ["fc_power_kw"],
                "conditions": {"efficiency": "below_baseline"},
                "description": "Fuel cell or electrolyzer efficiency below expected",
                "min_evidence_count": 1,
            },
            "FLOW_INCONSISTENCY": {
                "required_signals": ["flow_rate", "hydrogen_level_pct"],
                "conditions": {"flow_vs_level": "inconsistent"},
                "description": "Flow rate and level change are inconsistent",
                "min_evidence_count": 2,
            },
        }

    def get_default_limits(self) -> dict[str, tuple[float, float]]:
        return {
            "pressure_bar": (0.0, self.max_pressure_bar * 1.05),
            "temperature_c": (-40.0, self.max_temperature_c + 10.0),
            "hydrogen_level_pct": (0.0, 100.0),
            "flow_rate": (0.0, 1000.0),
        }
