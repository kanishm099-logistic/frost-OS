"""
Frost OS Module 05 — Fault Engine.

Returns possible fault hypotheses with evidence and confidence.
Multi-signal correlation strengthens evidence. Never claims a fault
is confirmed unless supported by explicit equipment diagnostics.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.config.settings import Settings
from app.equipment.base import EquipmentDiagnosticAdapter, FeatureVector, TelemetryWindow
from app.models.anomaly import Anomaly, AnomalySeverity, AnomalyType
from app.models.fault import FaultHypothesis, FaultReport
from app.models.health import DataQuality

logger = structlog.get_logger(__name__)

# Signal condition descriptors used in correlation
SIGNAL_CONDITION_MAP = {
    "high": lambda v, ref: v > ref * 1.2,
    "low": lambda v, ref: v < ref * 0.8,
    "elevated": lambda v, ref: v > ref * 1.1,
    "negative_large": lambda v, ref: v < -20.0,
    "negative_moderate": lambda v, ref: v < -10.0,
    "negative": lambda v, ref: v < 0.0,
    "below_freezing": lambda v, ref: v < 0.0,
    "above_threshold": lambda v, ref: v > ref,
}


class FaultEngine:
    """
    Classifies possible fault conditions based on anomaly patterns,
    equipment-specific signatures, and multi-signal correlation.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._fault_history: dict[str, list[FaultReport]] = {}

    def classify_faults(
        self,
        equipment_id: str,
        station_id: str,
        anomalies: list[Anomaly],
        features: FeatureVector | None,
        adapter: EquipmentDiagnosticAdapter | None,
        window: TelemetryWindow | None = None,
        data_quality: DataQuality = DataQuality.GOOD,
    ) -> FaultReport:
        """
        Generate fault hypotheses from anomaly patterns and fault signatures.

        Correlates multiple signals before classifying. Example:
        temperature↑ + vibration↑ + power_efficiency↓ → stronger mechanical risk.
        """
        hypotheses: list[FaultHypothesis] = []
        sensor_fault_suspected = False

        # Check for sensor faults first — important for differentiation
        sensor_anomalies = [a for a in anomalies if a.type == AnomalyType.SENSOR_FAULT]
        if sensor_anomalies:
            sensor_fault_suspected = True
            for sa in sensor_anomalies:
                hypotheses.append(FaultHypothesis(
                    fault="SENSOR_FAULT",
                    confidence=min(0.9, sa.confidence),
                    evidence=sa.signals + sa.possible_causes[:2],
                    description=f"Sensor fault detected: {', '.join(sa.possible_causes[:2])}",
                    recommended_investigation=(
                        "Verify sensor readings manually. Check connections, "
                        "calibration, and communication links."
                    ),
                ))

        # Match against equipment-specific fault signatures
        if adapter is not None and features is not None:
            signatures = adapter.get_fault_signatures()
            for fault_name, sig_def in signatures.items():
                if fault_name == "SENSOR_ERROR" and sensor_fault_suspected:
                    continue  # Already handled above

                evidence_count, evidence_list = self._evaluate_signature(
                    fault_name, sig_def, anomalies, features,
                )

                min_required = sig_def.get("min_evidence_count", 2)
                if evidence_count >= min_required:
                    # Scale confidence by evidence strength
                    base_confidence = min(0.9, evidence_count / max(min_required * 2, 3))

                    # Reduce confidence if sensor fault suspected
                    if sensor_fault_suspected:
                        base_confidence *= 0.6

                    hypotheses.append(FaultHypothesis(
                        fault=fault_name,
                        confidence=round(base_confidence, 2),
                        evidence=evidence_list,
                        description=sig_def.get("description", ""),
                        recommended_investigation=self._generate_recommendation(fault_name),
                    ))

        # Multi-signal correlation boost
        hypotheses = self._apply_correlation_boost(hypotheses, anomalies, features)

        # Sort by confidence (highest first)
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)

        # Determine primary fault
        primary = hypotheses[0].fault if hypotheses and hypotheses[0].confidence > 0.3 else None

        report = FaultReport(
            equipment_id=equipment_id,
            station_id=station_id,
            timestamp=datetime.now(timezone.utc),
            hypotheses=hypotheses,
            data_quality=data_quality,
            primary_fault=primary,
            sensor_fault_suspected=sensor_fault_suspected,
        )

        # Track history
        if equipment_id not in self._fault_history:
            self._fault_history[equipment_id] = []
        self._fault_history[equipment_id].append(report)
        if len(self._fault_history[equipment_id]) > 50:
            self._fault_history[equipment_id] = self._fault_history[equipment_id][-50:]

        return report

    def _evaluate_signature(
        self,
        fault_name: str,
        sig_def: dict[str, Any],
        anomalies: list[Anomaly],
        features: FeatureVector,
    ) -> tuple[int, list[str]]:
        """
        Evaluate how well current anomalies match a fault signature.
        Returns (evidence_count, evidence_descriptions).
        """
        evidence_count = 0
        evidence_list: list[str] = []

        required_signals = sig_def.get("required_signals", [])
        for sig in required_signals:
            # Check if any anomaly involves this signal
            for a in anomalies:
                if sig in a.signals:
                    evidence_count += 1
                    evidence_list.append(f"{sig}_anomaly({a.type.value})")
                    break

        # Check feature-based conditions
        conditions = sig_def.get("conditions", {})
        for condition_key, condition_val in conditions.items():
            feat_val = features.features.get(condition_key)
            if feat_val is not None:
                if isinstance(condition_val, str):
                    # Simple heuristic condition matching
                    if "negative" in condition_val and feat_val < 0:
                        evidence_count += 1
                        evidence_list.append(f"{condition_key}={feat_val:.2f}")
                    elif "elevated" in condition_val and feat_val > 0:
                        evidence_count += 1
                        evidence_list.append(f"{condition_key}_elevated")
                    elif "below_freezing" in condition_val and feat_val < 0:
                        evidence_count += 1
                        evidence_list.append(f"{condition_key}_below_freezing({feat_val:.1f}°C)")
                    elif "above_threshold" in condition_val:
                        evidence_count += 1
                        evidence_list.append(f"{condition_key}_above_threshold")
                    elif "low" in condition_val and feat_val < 0.85:
                        evidence_count += 1
                        evidence_list.append(f"{condition_key}_low({feat_val:.2f})")

        return evidence_count, evidence_list

    def _apply_correlation_boost(
        self,
        hypotheses: list[FaultHypothesis],
        anomalies: list[Anomaly],
        features: FeatureVector | None,
    ) -> list[FaultHypothesis]:
        """
        Boost confidence when multiple correlated signals support the same fault.

        Example: temperature↑ + vibration↑ + power_efficiency↓ → +15% confidence
        """
        if features is None or not anomalies:
            return hypotheses

        # Check for mechanical risk correlation pattern
        temp_high = any("temperature" in s for a in anomalies for s in a.signals
                        if a.severity in (AnomalySeverity.MEDIUM, AnomalySeverity.HIGH, AnomalySeverity.CRITICAL))
        vibration_high = any("vibration" in s for a in anomalies for s in a.signals
                            if a.severity in (AnomalySeverity.MEDIUM, AnomalySeverity.HIGH, AnomalySeverity.CRITICAL))
        power_low = features.features.get("power_curve_residual_pct", 0) < -15

        correlation_count = sum([temp_high, vibration_high, power_low])

        if correlation_count >= 2:
            for h in hypotheses:
                if h.fault in ("GEARBOX_WEAR", "BLADE_DAMAGE", "TURBINE_ICING", "THERMAL_ANOMALY"):
                    boost = 0.1 * (correlation_count - 1)
                    h_dict = h.model_dump()
                    h_dict["confidence"] = min(0.95, h.confidence + boost)
                    h_dict["evidence"] = h.evidence + [
                        f"multi_signal_correlation({correlation_count}_signals)"
                    ]
                    hypotheses[hypotheses.index(h)] = FaultHypothesis(**h_dict)

        return hypotheses

    def _generate_recommendation(self, fault_name: str) -> str:
        """Generate investigation recommendation for a fault type."""
        recommendations = {
            "TURBINE_ICING": "Inspect turbine blades for ice accumulation. Check de-icing system status.",
            "BLADE_DAMAGE": "Schedule visual blade inspection. Review vibration trend history.",
            "GEARBOX_WEAR": "Check gearbox oil temperature and vibration spectrum analysis.",
            "YAW_MISALIGNMENT": "Verify yaw motor and bearing. Compare nacelle position with wind direction.",
            "PANEL_DEGRADATION": "Compare IV-curve measurements. Check for discoloration or delamination.",
            "INVERTER_FAULT": "Review inverter fault codes and error logs. Check cooling system.",
            "SOILING": "Inspect panels for snow, dust, or debris. Schedule cleaning if safe.",
            "CELL_IMBALANCE": "Run cell-level voltage balancing test. Check BMS logs.",
            "THERMAL_ANOMALY": "Verify battery cooling system. Check ambient conditions.",
            "CAPACITY_FADE": "Run capacity test cycle. Compare with commissioning data.",
            "PRESSURE_ANOMALY": "Check pressure relief valves and tank integrity.",
            "LEAK_INDICATOR": "Inspect hydrogen system connections and seals. Use leak detector.",
            "EFFICIENCY_LOSS": "Check inverter components and cooling. Review operating profile.",
            "THERMAL_STRESS": "Verify cooling fans and heat sinks. Check for blocked vents.",
        }
        return recommendations.get(fault_name, "Schedule equipment inspection and review diagnostic data.")

    def get_fault_history(self, equipment_id: str, limit: int = 20) -> list[FaultReport]:
        """Retrieve fault classification history."""
        return self._fault_history.get(equipment_id, [])[-limit:]
