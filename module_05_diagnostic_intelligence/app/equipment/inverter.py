"""
Frost OS Module 05 — Inverter/Converter Diagnostic Adapter.

Monitors input/output power, voltage, current, frequency, temperature,
efficiency, and fault codes for power conversion equipment.
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


class InverterDiagnosticAdapter(EquipmentDiagnosticAdapter):
    """Diagnostic adapter for inverter and converter assets."""

    def __init__(
        self,
        nominal_efficiency: float = 0.96,
        efficiency_warning_threshold: float = 0.90,
        max_temperature_c: float = 65.0,
        frequency_tolerance_hz: float = 0.5,
        nominal_frequency_hz: float = 50.0,
    ) -> None:
        self.nominal_efficiency = nominal_efficiency
        self.efficiency_warning_threshold = efficiency_warning_threshold
        self.max_temperature_c = max_temperature_c
        self.frequency_tolerance_hz = frequency_tolerance_hz
        self.nominal_frequency_hz = nominal_frequency_hz

    def extract_features(
        self,
        window: TelemetryWindow,
        baseline: OperatingBaseline | None = None,
    ) -> FeatureVector:
        features: dict[str, float] = {}
        feature_names = [
            "input_power_kw", "output_power_kw", "efficiency",
            "voltage_v_mean", "current_a_mean",
            "frequency_hz_mean", "frequency_deviation_hz",
            "temperature_c_mean", "temperature_c_max",
            "power_factor",
        ]

        in_sig = window.get_signal("input_power_kw")
        out_sig = window.get_signal("output_power_kw") or window.get_signal("power_kw")

        features["input_power_kw"] = in_sig.mean if in_sig and not in_sig.is_empty() else 0.0
        features["output_power_kw"] = out_sig.mean if out_sig and not out_sig.is_empty() else 0.0

        if features["input_power_kw"] > 0.5:
            features["efficiency"] = features["output_power_kw"] / features["input_power_kw"]
        else:
            features["efficiency"] = 1.0

        v_sig = window.get_signal("voltage_v")
        features["voltage_v_mean"] = v_sig.mean if v_sig and not v_sig.is_empty() else 0.0

        c_sig = window.get_signal("current_a")
        features["current_a_mean"] = c_sig.mean if c_sig and not c_sig.is_empty() else 0.0

        f_sig = window.get_signal("frequency_hz")
        if f_sig and not f_sig.is_empty():
            features["frequency_hz_mean"] = f_sig.mean
            features["frequency_deviation_hz"] = abs(f_sig.mean - self.nominal_frequency_hz)
        else:
            features["frequency_hz_mean"] = self.nominal_frequency_hz
            features["frequency_deviation_hz"] = 0.0

        t_sig = window.get_signal("temperature_c")
        features["temperature_c_mean"] = t_sig.mean if t_sig and not t_sig.is_empty() else 30.0
        features["temperature_c_max"] = (
            float(np.nanmax(t_sig.values)) if t_sig and not t_sig.is_empty() else 30.0
        )

        features["power_factor"] = 1.0

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

        # Efficiency check
        in_sig = window.get_signal("input_power_kw")
        out_sig = window.get_signal("output_power_kw") or window.get_signal("power_kw")
        if in_sig and out_sig and not in_sig.is_empty() and not out_sig.is_empty():
            signals_checked.extend(["input_power_kw", "output_power_kw"])
            if in_sig.mean > 1.0:
                eff = out_sig.mean / in_sig.mean
                if eff < self.efficiency_warning_threshold:
                    severity = AnomalySeverity.MEDIUM
                    if eff < 0.80:
                        severity = AnomalySeverity.HIGH
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.RESIDUAL_DEVIATION,
                        severity=severity,
                        score=min(1.0, (self.nominal_efficiency - eff) / 0.2),
                        confidence=0.8,
                        observed_value=eff,
                        expected_value=self.nominal_efficiency,
                        residual=eff - self.nominal_efficiency,
                        signals=["input_power_kw", "output_power_kw"],
                        possible_causes=["component_degradation", "thermal_derating", "fault"],
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
                    possible_causes=["cooling_failure", "overload", "ambient_heat"],
                    detection_layer="rule_check",
                ))

        # Frequency deviation
        if window.has_signal("frequency_hz"):
            signals_checked.append("frequency_hz")
            f_sig = window.get_signal("frequency_hz")
            deviation = abs(f_sig.latest - self.nominal_frequency_hz)
            if deviation > self.frequency_tolerance_hz:
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.RESIDUAL_DEVIATION,
                    severity=AnomalySeverity.MEDIUM,
                    score=min(1.0, deviation / 2.0),
                    confidence=0.75,
                    observed_value=f_sig.latest,
                    expected_value=self.nominal_frequency_hz,
                    signals=["frequency_hz"],
                    possible_causes=["grid_instability", "inverter_control_issue", "overload"],
                    detection_layer="rule_check",
                ))

        return RuleCheckResult(
            anomalies=anomalies, warnings=warnings, signals_checked=signals_checked,
        )

    def compute_expected(
        self, conditions: dict[str, float], equipment: Equipment,
    ) -> ExpectedBehavior:
        input_power = conditions.get("input_power_kw", 0.0)
        return ExpectedBehavior(
            expected_values={
                "output_power_kw": input_power * self.nominal_efficiency,
                "frequency_hz": self.nominal_frequency_hz,
            },
            conditions=conditions,
            model_type="physics",
            confidence=0.85,
        )

    def get_fault_signatures(self) -> dict[str, dict[str, Any]]:
        return {
            "EFFICIENCY_LOSS": {
                "required_signals": ["input_power_kw", "output_power_kw"],
                "conditions": {"efficiency": "below_threshold"},
                "description": "Power conversion efficiency below expected",
                "min_evidence_count": 1,
            },
            "THERMAL_STRESS": {
                "required_signals": ["temperature_c"],
                "conditions": {"temperature": "above_limit"},
                "description": "Inverter operating above thermal limits",
                "min_evidence_count": 1,
            },
            "POWER_MISMATCH": {
                "required_signals": ["input_power_kw", "output_power_kw"],
                "conditions": {"power_balance": "inconsistent"},
                "description": "Input/output power balance inconsistency",
                "min_evidence_count": 1,
            },
            "FREQUENCY_DEVIATION": {
                "required_signals": ["frequency_hz"],
                "conditions": {"frequency": "outside_tolerance"},
                "description": "Output frequency deviating from nominal",
                "min_evidence_count": 1,
            },
        }

    def get_default_limits(self) -> dict[str, tuple[float, float]]:
        return {
            "temperature_c": (-20.0, self.max_temperature_c + 10.0),
            "frequency_hz": (45.0, 55.0),
            "voltage_v": (0.0, 1000.0),
        }
