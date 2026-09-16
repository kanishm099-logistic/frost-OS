"""
Frost OS Module 05 — Solar Array Diagnostic Adapter.

Implements irradiance-based expected generation, temperature-adjusted output,
panel degradation tracking, and cloud/weather vs equipment fault differentiation.
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


class SolarArrayAdapter(EquipmentDiagnosticAdapter):
    """Diagnostic adapter for solar PV array assets."""

    def __init__(
        self,
        installed_capacity_kw: float = 80.0,
        panel_efficiency: float = 0.19,
        panel_area_m2: float = 420.0,
        temp_coefficient: float = -0.004,
        degradation_rate_per_year: float = 0.005,
        output_deviation_threshold_pct: float = 20.0,
    ) -> None:
        self.installed_capacity_kw = installed_capacity_kw
        self.panel_efficiency = panel_efficiency
        self.panel_area_m2 = panel_area_m2
        self.temp_coefficient = temp_coefficient
        self.degradation_rate_per_year = degradation_rate_per_year
        self.output_deviation_threshold_pct = output_deviation_threshold_pct

    def expected_generation(
        self,
        irradiance_wm2: float,
        temperature_c: float = 25.0,
        age_years: float = 0.0,
    ) -> float:
        """
        Compute expected PV generation from irradiance and conditions.

        P_expected = irradiance × area × efficiency × temp_factor × age_factor
        where temp_factor = 1 + temp_coefficient × (T - 25)
              age_factor = 1 - degradation_rate × age_years
        """
        if irradiance_wm2 <= 0:
            return 0.0

        temp_factor = 1.0 + self.temp_coefficient * (temperature_c - 25.0)
        age_factor = max(0.5, 1.0 - self.degradation_rate_per_year * age_years)

        power_w = irradiance_wm2 * self.panel_area_m2 * self.panel_efficiency * temp_factor * age_factor
        power_kw = power_w / 1000.0

        return min(power_kw, self.installed_capacity_kw)

    def extract_features(
        self,
        window: TelemetryWindow,
        baseline: OperatingBaseline | None = None,
    ) -> FeatureVector:
        """Extract solar array diagnostic features."""
        features: dict[str, float] = {}
        feature_names = [
            "power_kw_mean", "power_kw_std",
            "irradiance_mean", "irradiance_std", "irradiance_variability",
            "temperature_c_mean",
            "expected_power_kw", "residual_kw", "residual_pct",
            "efficiency_ratio",
            "output_stability",
        ]

        power_sig = window.get_signal("power_kw")
        irr_sig = window.get_signal("irradiance_wm2")
        temp_sig = window.get_signal("temperature_c")

        p_mean = power_sig.mean if power_sig and not power_sig.is_empty() else 0.0
        p_std = power_sig.std if power_sig and not power_sig.is_empty() else 0.0
        features["power_kw_mean"] = p_mean
        features["power_kw_std"] = p_std

        irr_mean = irr_sig.mean if irr_sig and not irr_sig.is_empty() else 0.0
        irr_std = irr_sig.std if irr_sig and not irr_sig.is_empty() else 0.0
        features["irradiance_mean"] = irr_mean
        features["irradiance_std"] = irr_std
        features["irradiance_variability"] = (irr_std / irr_mean) if irr_mean > 10.0 else 0.0

        temp_mean = temp_sig.mean if temp_sig and not temp_sig.is_empty() else 25.0
        features["temperature_c_mean"] = temp_mean

        expected = self.expected_generation(irr_mean, temp_mean)
        features["expected_power_kw"] = expected
        features["residual_kw"] = p_mean - expected
        features["residual_pct"] = (
            ((p_mean - expected) / expected * 100.0) if expected > 0.5 else 0.0
        )
        features["efficiency_ratio"] = (p_mean / expected) if expected > 0.5 else 1.0
        features["output_stability"] = 1.0 - min(1.0, p_std / max(p_mean, 1.0))

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
        """Apply solar array deterministic rule checks."""
        anomalies: list[Anomaly] = []
        warnings: list[str] = []
        signals_checked: list[str] = []
        now = datetime.now(timezone.utc)

        # Output vs irradiance check
        if window.has_signals("power_kw", "irradiance_wm2"):
            signals_checked.extend(["power_kw", "irradiance_wm2"])
            power_sig = window.get_signal("power_kw")
            irr_sig = window.get_signal("irradiance_wm2")
            temp_sig = window.get_signal("temperature_c")
            temp = temp_sig.mean if temp_sig and not temp_sig.is_empty() else 25.0

            actual = power_sig.mean
            expected = self.expected_generation(irr_sig.mean, temp)

            # Only flag if irradiance is sufficient (not night/heavy cloud)
            if expected > 1.0:
                deviation_pct = ((actual - expected) / expected) * 100.0

                # Check if irradiance variability suggests cloud effects
                irr_variability = (irr_sig.std / irr_sig.mean) if irr_sig.mean > 10.0 else 0.0
                is_cloud_effect = irr_variability > 0.3

                if deviation_pct < -self.output_deviation_threshold_pct and not is_cloud_effect:
                    severity = AnomalySeverity.MEDIUM
                    if deviation_pct < -40.0:
                        severity = AnomalySeverity.HIGH

                    causes = ["panel_degradation", "soiling", "shading", "inverter_issue"]
                    if is_cloud_effect:
                        causes = ["cloud_weather_effect"]
                        severity = AnomalySeverity.INFO

                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.RESIDUAL_DEVIATION,
                        severity=severity,
                        score=min(1.0, abs(deviation_pct) / 80.0),
                        confidence=0.7 if not is_cloud_effect else 0.3,
                        observed_value=actual,
                        expected_value=expected,
                        residual=actual - expected,
                        signals=["power_kw", "irradiance_wm2"],
                        possible_causes=causes,
                        detection_layer="rule_check",
                    ))
                elif is_cloud_effect and deviation_pct < -self.output_deviation_threshold_pct:
                    warnings.append(
                        f"Output {deviation_pct:.1f}% below expected but high irradiance "
                        f"variability ({irr_variability:.2f}) suggests weather effect"
                    )

        # Inverter efficiency check
        if window.has_signals("power_kw", "dc_power_kw"):
            signals_checked.append("dc_power_kw")
            ac_sig = window.get_signal("power_kw")
            dc_sig = window.get_signal("dc_power_kw")
            if dc_sig.mean > 1.0:
                efficiency = ac_sig.mean / dc_sig.mean
                if efficiency < 0.85:
                    anomalies.append(Anomaly(
                        equipment_id=window.equipment_id,
                        station_id=window.station_id,
                        timestamp=now,
                        type=AnomalyType.RESIDUAL_DEVIATION,
                        severity=AnomalySeverity.MEDIUM,
                        score=0.6,
                        confidence=0.75,
                        observed_value=efficiency,
                        expected_value=0.95,
                        residual=efficiency - 0.95,
                        signals=["power_kw", "dc_power_kw"],
                        possible_causes=["inverter_degradation", "inverter_fault"],
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
        """Compute expected solar output from conditions."""
        irradiance = conditions.get("irradiance_wm2", 0.0)
        temperature = conditions.get("temperature_c", 25.0)
        age_years = conditions.get("age_years", 0.0)

        expected_power = self.expected_generation(irradiance, temperature, age_years)

        return ExpectedBehavior(
            expected_values={
                "power_kw": expected_power,
                "generating": 1.0 if irradiance > 10.0 else 0.0,
            },
            conditions=conditions,
            model_type="physics",
            confidence=0.8,
        )

    def get_fault_signatures(self) -> dict[str, dict[str, Any]]:
        """Return solar array fault signatures."""
        return {
            "PANEL_DEGRADATION": {
                "required_signals": ["power_kw", "irradiance_wm2"],
                "conditions": {
                    "residual_pct": "persistently_negative",
                    "irradiance_variability": "low",
                },
                "description": "Gradual panel efficiency loss exceeding normal aging",
                "min_evidence_count": 2,
            },
            "INVERTER_FAULT": {
                "required_signals": ["power_kw"],
                "optional_signals": ["dc_power_kw", "inverter_temperature_c"],
                "conditions": {
                    "efficiency_ratio": "low",
                },
                "description": "Inverter efficiency below expected, possible component degradation",
                "min_evidence_count": 1,
            },
            "SOILING": {
                "required_signals": ["power_kw", "irradiance_wm2"],
                "conditions": {
                    "residual_pct": "moderately_negative",
                    "gradual_onset": "true",
                },
                "description": "Snow, dust, or debris accumulation reducing panel output",
                "min_evidence_count": 2,
            },
            "SHADING": {
                "required_signals": ["power_kw", "irradiance_wm2"],
                "conditions": {
                    "time_dependent_loss": "true",
                },
                "description": "Partial shading causing time-dependent output reduction",
                "min_evidence_count": 2,
            },
            "SENSOR_DISAGREEMENT": {
                "required_signals": ["irradiance_wm2"],
                "conditions": {
                    "sensor_disagreement": "true",
                },
                "description": "Irradiance sensors disagree, possible sensor fault",
                "min_evidence_count": 1,
            },
        }

    def get_default_limits(self) -> dict[str, tuple[float, float]]:
        return {
            "power_kw": (0.0, self.installed_capacity_kw * 1.1),
            "irradiance_wm2": (0.0, 1500.0),
            "temperature_c": (-80.0, 90.0),
        }
