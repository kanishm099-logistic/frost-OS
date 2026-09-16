"""
Frost OS Module 05 — Battery Diagnostic Adapter.

Monitors SOC, SOH, voltage, temperature, current, charge/discharge behavior.
Never infers thermal runaway from a single noisy reading — requires correlated
temperature + voltage + current evidence.
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


class BatteryDiagnosticAdapter(EquipmentDiagnosticAdapter):
    """Diagnostic adapter for battery energy storage systems."""

    def __init__(
        self,
        capacity_kwh: float = 6000.0,
        temp_high_c: float = 45.0,
        temp_critical_c: float = 55.0,
        voltage_imbalance_threshold_pct: float = 5.0,
        soc_rate_threshold_pct_per_min: float = 2.0,
    ) -> None:
        self.capacity_kwh = capacity_kwh
        self.temp_high_c = temp_high_c
        self.temp_critical_c = temp_critical_c
        self.voltage_imbalance_threshold_pct = voltage_imbalance_threshold_pct
        self.soc_rate_threshold_pct_per_min = soc_rate_threshold_pct_per_min

    def extract_features(
        self,
        window: TelemetryWindow,
        baseline: OperatingBaseline | None = None,
    ) -> FeatureVector:
        """Extract battery diagnostic features."""
        features: dict[str, float] = {}
        feature_names = [
            "soc_pct", "soc_rate_of_change", "soh_pct",
            "voltage_v_mean", "voltage_v_std",
            "current_a_mean", "current_a_std",
            "temperature_c_mean", "temperature_c_max", "temperature_c_rate",
            "power_kw_mean",
            "charge_efficiency", "discharge_efficiency",
        ]

        # SOC
        soc_sig = window.get_signal("soc_pct")
        if soc_sig and not soc_sig.is_empty():
            features["soc_pct"] = soc_sig.latest
            if soc_sig.count >= 2:
                soc_change = float(soc_sig.values[-1] - soc_sig.values[0])
                duration_min = max(1.0, soc_sig.count * 5.0 / 60.0)
                features["soc_rate_of_change"] = soc_change / duration_min
            else:
                features["soc_rate_of_change"] = 0.0
        else:
            features["soc_pct"] = 50.0
            features["soc_rate_of_change"] = 0.0

        # SOH
        soh_sig = window.get_signal("soh_pct")
        features["soh_pct"] = soh_sig.latest if soh_sig and not soh_sig.is_empty() else 100.0

        # Voltage
        volt_sig = window.get_signal("voltage_v")
        features["voltage_v_mean"] = volt_sig.mean if volt_sig and not volt_sig.is_empty() else 0.0
        features["voltage_v_std"] = volt_sig.std if volt_sig and not volt_sig.is_empty() else 0.0

        # Current
        curr_sig = window.get_signal("current_a")
        features["current_a_mean"] = curr_sig.mean if curr_sig and not curr_sig.is_empty() else 0.0
        features["current_a_std"] = curr_sig.std if curr_sig and not curr_sig.is_empty() else 0.0

        # Temperature
        temp_sig = window.get_signal("temperature_c")
        if temp_sig and not temp_sig.is_empty():
            features["temperature_c_mean"] = temp_sig.mean
            features["temperature_c_max"] = float(np.nanmax(temp_sig.values))
            if temp_sig.count >= 2:
                temp_rate = float(temp_sig.values[-1] - temp_sig.values[0])
                features["temperature_c_rate"] = temp_rate
            else:
                features["temperature_c_rate"] = 0.0
        else:
            features["temperature_c_mean"] = 20.0
            features["temperature_c_max"] = 20.0
            features["temperature_c_rate"] = 0.0

        # Power
        power_sig = window.get_signal("power_kw")
        features["power_kw_mean"] = power_sig.mean if power_sig and not power_sig.is_empty() else 0.0

        # Efficiency estimates (simplified)
        features["charge_efficiency"] = 0.95
        features["discharge_efficiency"] = 0.95

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
        """Apply battery deterministic rule checks."""
        anomalies: list[Anomaly] = []
        warnings: list[str] = []
        signals_checked: list[str] = []
        now = datetime.now(timezone.utc)

        # Temperature anomaly — requires correlated evidence for escalation
        if window.has_signal("temperature_c"):
            signals_checked.append("temperature_c")
            temp_sig = window.get_signal("temperature_c")
            temp_max = float(np.nanmax(temp_sig.values))

            if temp_max > self.temp_critical_c:
                # CRITICAL temperature — but verify with multiple readings
                consistent_high = np.sum(temp_sig.values > self.temp_critical_c)
                if consistent_high >= 2:
                    # Corroborated by multiple readings — flag HIGH
                    evidence_signals = ["temperature_c"]
                    severity = AnomalySeverity.HIGH

                    # Check for correlated voltage/current anomaly before escalating to CRITICAL
                    has_voltage_anomaly = False
                    has_current_anomaly = False
                    if window.has_signal("voltage_v"):
                        v_sig = window.get_signal("voltage_v")
                        if v_sig.std > v_sig.mean * 0.05:
                            has_voltage_anomaly = True
                            evidence_signals.append("voltage_v")
                    if window.has_signal("current_a"):
                        c_sig = window.get_signal("current_a")
                        if abs(c_sig.mean) > 0 and c_sig.std / abs(c_sig.mean) > 0.3:
                            has_current_anomaly = True
                            evidence_signals.append("current_a")

                    if has_voltage_anomaly or has_current_anomaly:
                        severity = AnomalySeverity.CRITICAL

                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.LIMIT_VIOLATION,
                        severity=severity,
                        score=0.9 if severity == AnomalySeverity.CRITICAL else 0.7,
                        confidence=0.85 if consistent_high >= 3 else 0.65,
                        observed_value=temp_max,
                        expected_value=self.temp_critical_c,
                        residual=temp_max - self.temp_critical_c,
                        signals=evidence_signals,
                        possible_causes=["thermal_anomaly", "cooling_failure", "high_discharge_rate"],
                        detection_layer="rule_check",
                    ))
                else:
                    warnings.append(
                        f"Single high temperature reading ({temp_max:.1f}°C) — "
                        f"monitoring for confirmation before escalation"
                    )
            elif temp_max > self.temp_high_c:
                anomalies.append(Anomaly(
                    equipment_id=window.equipment_id,
                    station_id=window.station_id,
                    timestamp=now,
                    type=AnomalyType.LIMIT_VIOLATION,
                    severity=AnomalySeverity.MEDIUM,
                    score=0.5,
                    confidence=0.8,
                    observed_value=temp_max,
                    expected_value=self.temp_high_c,
                    residual=temp_max - self.temp_high_c,
                    signals=["temperature_c"],
                    possible_causes=["elevated_temperature", "high_charge_rate", "ambient_conditions"],
                    detection_layer="rule_check",
                ))

        # SOC rate of change check
        if window.has_signal("soc_pct"):
            signals_checked.append("soc_pct")
            soc_sig = window.get_signal("soc_pct")
            if soc_sig.count >= 2:
                soc_change = abs(float(soc_sig.values[-1] - soc_sig.values[0]))
                duration_min = max(1.0, soc_sig.count * 5.0 / 60.0)
                rate = soc_change / duration_min
                if rate > self.soc_rate_threshold_pct_per_min:
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.RATE_OF_CHANGE,
                        severity=AnomalySeverity.MEDIUM,
                        score=0.6,
                        confidence=0.7,
                        observed_value=rate,
                        expected_value=self.soc_rate_threshold_pct_per_min,
                        residual=rate - self.soc_rate_threshold_pct_per_min,
                        signals=["soc_pct"],
                        possible_causes=["sensor_drift", "capacity_loss", "unexpected_load"],
                        detection_layer="rule_check",
                    ))

        # Voltage imbalance (if cell-level data available)
        if window.has_signals("voltage_v", "voltage_v_min", "voltage_v_max"):
            signals_checked.extend(["voltage_v_min", "voltage_v_max"])
            v_min_sig = window.get_signal("voltage_v_min")
            v_max_sig = window.get_signal("voltage_v_max")
            v_mean_sig = window.get_signal("voltage_v")
            if v_mean_sig.mean > 0:
                imbalance_pct = (
                    (v_max_sig.latest - v_min_sig.latest) / v_mean_sig.mean * 100.0
                )
                if imbalance_pct > self.voltage_imbalance_threshold_pct:
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.RESIDUAL_DEVIATION,
                        severity=AnomalySeverity.MEDIUM,
                        score=min(1.0, imbalance_pct / 20.0),
                        confidence=0.8,
                        observed_value=imbalance_pct,
                        expected_value=self.voltage_imbalance_threshold_pct,
                        signals=["voltage_v", "voltage_v_min", "voltage_v_max"],
                        possible_causes=["cell_imbalance", "weak_cell", "connection_issue"],
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
        """Compute expected battery behavior."""
        soc = conditions.get("soc_pct", 50.0)
        return ExpectedBehavior(
            expected_values={
                "temperature_c": 25.0,
                "available_energy_kwh": self.capacity_kwh * (soc / 100.0) * 0.85,
            },
            conditions=conditions,
            model_type="physics",
            confidence=0.7,
        )

    def get_fault_signatures(self) -> dict[str, dict[str, Any]]:
        """Return battery fault signatures."""
        return {
            "CELL_IMBALANCE": {
                "required_signals": ["voltage_v"],
                "optional_signals": ["voltage_v_min", "voltage_v_max"],
                "conditions": {"voltage_imbalance": "above_threshold"},
                "description": "Cell voltage imbalance indicating weak cell or connection issue",
                "min_evidence_count": 1,
            },
            "THERMAL_ANOMALY": {
                "required_signals": ["temperature_c"],
                "optional_signals": ["voltage_v", "current_a"],
                "conditions": {
                    "temperature_c": "above_high_threshold",
                    "correlated_evidence": "required_for_critical",
                },
                "description": (
                    "Abnormal battery temperature. CRITICAL only with correlated "
                    "voltage/current evidence — single noisy reading is not sufficient."
                ),
                "min_evidence_count": 2,
            },
            "CAPACITY_FADE": {
                "required_signals": ["soh_pct"],
                "conditions": {"soh_trend": "declining"},
                "description": "Progressive capacity loss beyond normal aging",
                "min_evidence_count": 1,
            },
            "CHARGE_INEFFICIENCY": {
                "required_signals": ["power_kw", "soc_pct"],
                "conditions": {"charge_efficiency": "below_expected"},
                "description": "Charge/discharge round-trip efficiency degradation",
                "min_evidence_count": 2,
            },
            "SENSOR_FAULT": {
                "required_signals": ["soc_pct"],
                "conditions": {"soc_rate": "physically_impossible"},
                "description": "Battery sensor providing implausible readings",
                "min_evidence_count": 1,
            },
        }

    def get_default_limits(self) -> dict[str, tuple[float, float]]:
        return {
            "soc_pct": (0.0, 100.0),
            "soh_pct": (0.0, 100.0),
            "temperature_c": (-30.0, self.temp_critical_c + 10.0),
            "voltage_v": (0.0, 1000.0),
            "current_a": (-2000.0, 2000.0),
        }
