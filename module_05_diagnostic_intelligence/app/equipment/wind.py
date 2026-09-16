"""
Frost OS Module 05 — Wind Turbine Diagnostic Adapter.

Implements power-curve deviation analysis, vibration monitoring, RPM tracking,
icing probability estimation, and wind-specific fault signature detection.
Icing probability is clearly labelled as a model estimate, not confirmed truth.
"""

from __future__ import annotations

import math
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


class WindTurbineAdapter(EquipmentDiagnosticAdapter):
    """Diagnostic adapter for wind turbine assets."""

    def __init__(
        self,
        rated_power_kw: float = 120.0,
        cut_in_speed_ms: float = 3.0,
        rated_speed_ms: float = 12.0,
        cut_out_speed_ms: float = 25.0,
        icing_temp_threshold_c: float = -5.0,
        power_curve_deviation_pct: float = 20.0,
    ) -> None:
        self.rated_power_kw = rated_power_kw
        self.cut_in_speed_ms = cut_in_speed_ms
        self.rated_speed_ms = rated_speed_ms
        self.cut_out_speed_ms = cut_out_speed_ms
        self.icing_temp_threshold_c = icing_temp_threshold_c
        self.power_curve_deviation_pct = power_curve_deviation_pct

    def power_curve(self, wind_speed: float) -> float:
        """
        Compute expected turbine power output from wind speed using
        a simplified cubic power curve model.

        P = P_rated × ((v - v_cut_in) / (v_rated - v_cut_in))^3
        for v_cut_in ≤ v < v_rated

        P = P_rated for v_rated ≤ v ≤ v_cut_out
        P = 0 for v < v_cut_in or v > v_cut_out
        """
        if wind_speed < self.cut_in_speed_ms or wind_speed > self.cut_out_speed_ms:
            return 0.0
        if wind_speed >= self.rated_speed_ms:
            return self.rated_power_kw
        ratio = (wind_speed - self.cut_in_speed_ms) / (self.rated_speed_ms - self.cut_in_speed_ms)
        return self.rated_power_kw * ratio ** 3

    def extract_features(
        self,
        window: TelemetryWindow,
        baseline: OperatingBaseline | None = None,
    ) -> FeatureVector:
        """Extract wind turbine diagnostic features."""
        features: dict[str, float] = {}
        feature_names = [
            "power_kw_mean", "power_kw_std", "wind_speed_mean", "wind_speed_std",
            "power_curve_residual", "power_curve_residual_pct",
            "vibration_mean", "vibration_std", "vibration_zscore",
            "rpm_mean", "rpm_std",
            "nacelle_temp_mean", "ambient_temp_mean",
            "temp_delta",
            "icing_indicator",
        ]

        # Power
        power_sig = window.get_signal("power_kw")
        if power_sig and not power_sig.is_empty():
            features["power_kw_mean"] = power_sig.mean
            features["power_kw_std"] = power_sig.std
        else:
            features["power_kw_mean"] = 0.0
            features["power_kw_std"] = 0.0

        # Wind speed
        wind_sig = window.get_signal("wind_speed_ms")
        if wind_sig and not wind_sig.is_empty():
            features["wind_speed_mean"] = wind_sig.mean
            features["wind_speed_std"] = wind_sig.std
        else:
            features["wind_speed_mean"] = 0.0
            features["wind_speed_std"] = 0.0

        # Power curve residual
        expected_power = self.power_curve(features["wind_speed_mean"])
        actual_power = features["power_kw_mean"]
        residual = actual_power - expected_power
        features["power_curve_residual"] = residual
        features["power_curve_residual_pct"] = (
            (residual / expected_power * 100.0) if expected_power > 1.0 else 0.0
        )

        # Vibration
        vib_sig = window.get_signal("vibration")
        if vib_sig and not vib_sig.is_empty():
            features["vibration_mean"] = vib_sig.mean
            features["vibration_std"] = vib_sig.std
            if baseline and "vibration" in baseline.expected_values:
                bv = baseline.expected_values["vibration"]
                baseline_std = bv.get("std", 1.0)
                if baseline_std > 0:
                    features["vibration_zscore"] = (
                        (vib_sig.mean - bv.get("mean", 0.0)) / baseline_std
                    )
                else:
                    features["vibration_zscore"] = 0.0
            else:
                features["vibration_zscore"] = 0.0
        else:
            features["vibration_mean"] = 0.0
            features["vibration_std"] = 0.0
            features["vibration_zscore"] = 0.0

        # RPM
        rpm_sig = window.get_signal("rpm")
        if rpm_sig and not rpm_sig.is_empty():
            features["rpm_mean"] = rpm_sig.mean
            features["rpm_std"] = rpm_sig.std
        else:
            features["rpm_mean"] = 0.0
            features["rpm_std"] = 0.0

        # Temperature
        nacelle_sig = window.get_signal("nacelle_temperature_c")
        ambient_sig = window.get_signal("ambient_temperature_c")
        nac_temp = nacelle_sig.mean if nacelle_sig and not nacelle_sig.is_empty() else 0.0
        amb_temp = ambient_sig.mean if ambient_sig and not ambient_sig.is_empty() else 0.0
        features["nacelle_temp_mean"] = nac_temp
        features["ambient_temp_mean"] = amb_temp
        features["temp_delta"] = nac_temp - amb_temp

        # Icing indicator (composite estimate)
        features["icing_indicator"] = self._estimate_icing_indicator(features)

        return FeatureVector(
            equipment_id=window.equipment_id,
            timestamp=window.window_end or datetime.now(timezone.utc),
            features=features,
            feature_names=feature_names,
        )

    def _estimate_icing_indicator(self, features: dict[str, float]) -> float:
        """
        Estimate icing probability from composite signals.

        This is a MODEL ESTIMATE, not a confirmed physical truth.
        Returns 0.0-1.0 icing indicator.
        """
        indicator = 0.0

        # Low ambient temperature contribution
        amb_temp = features.get("ambient_temp_mean", 10.0)
        if amb_temp < self.icing_temp_threshold_c:
            temp_factor = min(1.0, abs(amb_temp - self.icing_temp_threshold_c) / 20.0)
            indicator += 0.3 * temp_factor

        # Power curve negative residual (underperforming)
        residual_pct = features.get("power_curve_residual_pct", 0.0)
        if residual_pct < -self.power_curve_deviation_pct:
            power_factor = min(1.0, abs(residual_pct) / 50.0)
            indicator += 0.35 * power_factor

        # Vibration anomaly
        vib_zscore = features.get("vibration_zscore", 0.0)
        if abs(vib_zscore) > 2.0:
            indicator += 0.2 * min(1.0, abs(vib_zscore) / 5.0)

        # RPM anomaly vs expected
        rpm_mean = features.get("rpm_mean", 0.0)
        wind_speed = features.get("wind_speed_mean", 0.0)
        if wind_speed > self.cut_in_speed_ms and rpm_mean < 10.0:
            indicator += 0.15

        return min(1.0, indicator)

    def check_rules(
        self,
        window: TelemetryWindow,
        equipment: Equipment,
        baseline: OperatingBaseline | None = None,
    ) -> RuleCheckResult:
        """Apply wind turbine deterministic rule checks."""
        anomalies: list[Anomaly] = []
        warnings: list[str] = []
        signals_checked: list[str] = []
        now = datetime.now(timezone.utc)

        # Power curve deviation check
        if window.has_signals("power_kw", "wind_speed_ms"):
            signals_checked.extend(["power_kw", "wind_speed_ms"])
            power_sig = window.get_signal("power_kw")
            wind_sig = window.get_signal("wind_speed_ms")
            actual = power_sig.latest
            expected = self.power_curve(wind_sig.latest)

            if expected > 1.0:
                deviation_pct = ((actual - expected) / expected) * 100.0
                if abs(deviation_pct) > self.power_curve_deviation_pct:
                    severity = AnomalySeverity.MEDIUM
                    if abs(deviation_pct) > 40.0:
                        severity = AnomalySeverity.HIGH
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.RESIDUAL_DEVIATION,
                        severity=severity,
                        score=min(1.0, abs(deviation_pct) / 100.0),
                        confidence=0.8,
                        observed_value=actual,
                        expected_value=expected,
                        residual=actual - expected,
                        signals=["power_kw", "wind_speed_ms"],
                        possible_causes=["icing", "degradation", "curtailment", "sensor_error"],
                        detection_layer="rule_check",
                    ))

        # Vibration check
        if window.has_signal("vibration"):
            signals_checked.append("vibration")
            vib_sig = window.get_signal("vibration")
            limits = equipment.operating_limits
            if limits.max_vibration is not None and vib_sig.latest > limits.max_vibration:
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.LIMIT_VIOLATION,
                    severity=AnomalySeverity.HIGH,
                    score=0.8,
                    confidence=0.9,
                    observed_value=vib_sig.latest,
                    expected_value=limits.max_vibration,
                    residual=vib_sig.latest - limits.max_vibration,
                    signals=["vibration"],
                    possible_causes=["bearing_wear", "blade_damage", "icing", "foundation_issue"],
                    detection_layer="rule_check",
                ))

        # RPM consistency check
        if window.has_signals("rpm", "wind_speed_ms"):
            signals_checked.append("rpm")
            rpm_sig = window.get_signal("rpm")
            wind_sig = window.get_signal("wind_speed_ms")
            if wind_sig.latest > self.cut_in_speed_ms and rpm_sig.latest < 5.0:
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.RESIDUAL_DEVIATION,
                    severity=AnomalySeverity.MEDIUM,
                    score=0.6,
                    confidence=0.7,
                    observed_value=rpm_sig.latest,
                    expected_value=None,
                    signals=["rpm", "wind_speed_ms"],
                    possible_causes=["icing", "brake_engaged", "mechanical_failure"],
                    detection_layer="rule_check",
                ))

        # Nacelle overtemperature
        if window.has_signal("nacelle_temperature_c"):
            signals_checked.append("nacelle_temperature_c")
            temp_sig = window.get_signal("nacelle_temperature_c")
            max_temp = (equipment.operating_limits.max_temperature_c
                        if equipment.operating_limits.max_temperature_c is not None else 80.0)
            if temp_sig.latest > max_temp:
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.LIMIT_VIOLATION,
                    severity=AnomalySeverity.HIGH,
                    score=0.85,
                    confidence=0.9,
                    observed_value=temp_sig.latest,
                    expected_value=max_temp,
                    residual=temp_sig.latest - max_temp,
                    signals=["nacelle_temperature_c"],
                    possible_causes=["bearing_overheating", "gearbox_issue", "cooling_failure"],
                    detection_layer="rule_check",
                ))

        return RuleCheckResult(
            anomalies=anomalies,
            warnings=warnings,
            signals_checked=signals_checked,
        )

    def compute_expected(
        self,
        conditions: dict[str, float],
        equipment: Equipment,
    ) -> ExpectedBehavior:
        """Compute expected turbine behavior from wind conditions."""
        wind_speed = conditions.get("wind_speed_ms", 0.0)
        expected_power = self.power_curve(wind_speed)

        return ExpectedBehavior(
            expected_values={
                "power_kw": expected_power,
                "operating": 1.0 if self.cut_in_speed_ms <= wind_speed <= self.cut_out_speed_ms else 0.0,
            },
            conditions=conditions,
            model_type="physics",
            confidence=0.85,
        )

    def get_fault_signatures(self) -> dict[str, dict[str, Any]]:
        """Return wind turbine fault signatures."""
        return {
            "TURBINE_ICING": {
                "required_signals": ["power_kw", "wind_speed_ms"],
                "optional_signals": ["vibration", "rpm", "ambient_temperature_c"],
                "conditions": {
                    "power_curve_residual_pct": "negative_large",
                    "ambient_temperature_c": "below_freezing",
                },
                "description": (
                    "Ice accumulation on blades reduces aerodynamic performance. "
                    "Indicated by negative power curve residual with low ambient temperature. "
                    "NOTE: This is a model estimate, not confirmed physical truth."
                ),
                "min_evidence_count": 2,
            },
            "BLADE_DAMAGE": {
                "required_signals": ["vibration", "power_kw"],
                "conditions": {
                    "vibration": "elevated",
                    "power_curve_residual_pct": "negative",
                },
                "description": "Blade structural damage causing vibration and power loss",
                "min_evidence_count": 2,
            },
            "GEARBOX_WEAR": {
                "required_signals": ["vibration", "nacelle_temperature_c"],
                "conditions": {
                    "vibration": "elevated",
                    "nacelle_temperature_c": "elevated",
                },
                "description": "Gearbox bearing wear indicated by vibration and thermal anomaly",
                "min_evidence_count": 2,
            },
            "YAW_MISALIGNMENT": {
                "required_signals": ["power_kw", "wind_speed_ms", "wind_direction_deg"],
                "conditions": {
                    "power_curve_residual_pct": "negative_moderate",
                },
                "description": "Turbine nacelle not tracking wind direction properly",
                "min_evidence_count": 2,
            },
            "SENSOR_ERROR": {
                "required_signals": ["wind_speed_ms"],
                "conditions": {
                    "wind_sensor_disagreement": "true",
                },
                "description": "Wind sensor providing inconsistent or stale readings",
                "min_evidence_count": 1,
            },
        }

    def get_default_limits(self) -> dict[str, tuple[float, float]]:
        """Return default operating limits for wind turbines."""
        return {
            "power_kw": (0.0, self.rated_power_kw * 1.1),
            "wind_speed_ms": (0.0, 80.0),
            "vibration": (0.0, 10.0),
            "rpm": (0.0, 500.0),
            "nacelle_temperature_c": (-60.0, 80.0),
        }
