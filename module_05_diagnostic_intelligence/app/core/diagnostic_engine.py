"""
Frost OS Module 05 — Diagnostic Engine.

Orchestrates the full diagnostic pipeline by delegating to sub-engines.
This is NOT a monolith — each concern (telemetry, baseline, anomaly,
health, fault, risk, degradation) is handled by its own engine.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

from app.config.settings import Settings
from app.core.anomaly_engine import AnomalyEngine
from app.core.baseline_engine import BaselineEngine
from app.core.degradation_engine import DegradationEngine
from app.core.fault_engine import FaultEngine
from app.core.health_engine import HealthEngine
from app.core.risk_engine import RiskEngine
from app.core.telemetry_processor import TelemetryProcessor
from app.equipment.base import EquipmentDiagnosticAdapter
from app.equipment.battery import BatteryDiagnosticAdapter
from app.equipment.hydrogen import HydrogenSystemAdapter
from app.equipment.inverter import InverterDiagnosticAdapter
from app.equipment.sensor import SensorDiagnosticAdapter
from app.equipment.solar import SolarArrayAdapter
from app.equipment.wind import WindTurbineAdapter
from app.models.anomaly import Anomaly
from app.models.equipment import Equipment, EquipmentType
from app.models.fault import FaultHypothesis, FaultReport
from app.models.health import DataQuality, EquipmentHealth, HealthState
from app.models.risk import FailureRisk

logger = structlog.get_logger(__name__)


class DiagnosticResult:
    """
    Complete diagnostic result for a single equipment asset.

    Module 05 produces this as its primary output. Recommendations
    are informational only — Module 05 does NOT issue hardware commands.
    """

    def __init__(
        self,
        diagnostic_id: str | None = None,
        equipment_id: str = "",
        station_id: str = "",
        timestamp: datetime | None = None,
        health_score: float = 100.0,
        health_state: HealthState = HealthState.HEALTHY,
        anomaly_detected: bool = False,
        anomalies: list[Anomaly] | None = None,
        fault_hypotheses: list[FaultHypothesis] | None = None,
        failure_risk: FailureRisk | None = None,
        degradation: dict[str, Any] | None = None,
        data_quality: DataQuality = DataQuality.GOOD,
        recommended_investigation: list[str] | None = None,
        model_version: str = "v0.1.0",
    ) -> None:
        self.diagnostic_id = diagnostic_id or str(uuid.uuid4())
        self.equipment_id = equipment_id
        self.station_id = station_id
        self.timestamp = timestamp or datetime.now(timezone.utc)
        self.health_score = health_score
        self.health_state = health_state
        self.anomaly_detected = anomaly_detected
        self.anomalies = anomalies or []
        self.fault_hypotheses = fault_hypotheses or []
        self.failure_risk = failure_risk
        self.degradation = degradation or {}
        self.data_quality = data_quality
        self.recommended_investigation = recommended_investigation or []
        self.model_version = model_version

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for API responses."""
        return {
            "diagnostic_id": self.diagnostic_id,
            "equipment_id": self.equipment_id,
            "station_id": self.station_id,
            "timestamp": self.timestamp.isoformat(),
            "health_score": self.health_score,
            "health_state": self.health_state.value,
            "anomaly_detected": self.anomaly_detected,
            "anomalies": [a.model_dump(mode="json") for a in self.anomalies],
            "fault_hypotheses": [f.model_dump(mode="json") for f in self.fault_hypotheses],
            "failure_risk": self.failure_risk.model_dump(mode="json") if self.failure_risk else None,
            "degradation": self.degradation,
            "data_quality": self.data_quality.value,
            "recommended_investigation": self.recommended_investigation,
            "model_version": self.model_version,
        }


# ── Adapter registry ──────────────────────────────────────────────────

def _get_adapter(equipment_type: EquipmentType, settings: Settings) -> EquipmentDiagnosticAdapter:
    """Get the appropriate diagnostic adapter for an equipment type."""
    adapters: dict[EquipmentType, EquipmentDiagnosticAdapter] = {
        EquipmentType.WIND_TURBINE: WindTurbineAdapter(
            rated_power_kw=settings.wind_rated_power_kw,
            cut_in_speed_ms=settings.wind_cut_in_speed_ms,
            rated_speed_ms=settings.wind_rated_speed_ms,
            cut_out_speed_ms=settings.wind_cut_out_speed_ms,
            icing_temp_threshold_c=settings.wind_icing_temp_threshold_c,
            power_curve_deviation_pct=settings.wind_power_curve_deviation_pct,
        ),
        EquipmentType.SOLAR_ARRAY: SolarArrayAdapter(
            installed_capacity_kw=settings.solar_installed_capacity_kw,
            panel_efficiency=settings.solar_panel_efficiency,
            panel_area_m2=settings.solar_panel_area_m2,
            temp_coefficient=settings.solar_temp_coefficient,
        ),
        EquipmentType.BATTERY: BatteryDiagnosticAdapter(
            capacity_kwh=settings.battery_capacity_kwh,
            temp_high_c=settings.battery_temp_high_c,
            temp_critical_c=settings.battery_temp_critical_c,
            voltage_imbalance_threshold_pct=settings.battery_voltage_imbalance_threshold_pct,
        ),
        EquipmentType.HYDROGEN_TANK: HydrogenSystemAdapter(),
        EquipmentType.ELECTROLYZER: HydrogenSystemAdapter(),
        EquipmentType.FUEL_CELL: HydrogenSystemAdapter(),
        EquipmentType.INVERTER: InverterDiagnosticAdapter(),
        EquipmentType.CONVERTER: InverterDiagnosticAdapter(),
        EquipmentType.SENSOR: SensorDiagnosticAdapter(
            stale_threshold_seconds=settings.stale_sensor_threshold_seconds,
        ),
    }
    return adapters.get(equipment_type, SensorDiagnosticAdapter())


class DiagnosticEngine:
    """
    Orchestrates the full diagnostic pipeline.

    Pipeline steps:
    1. Load equipment config + adapter
    2. Telemetry processor: validate → clean → align
    3. Baseline engine: load expected behavior
    4. Equipment adapter: extract features
    5. Equipment adapter: rule checks
    6. Anomaly engine: 5-layer detection
    7. Health engine: compute score
    8. Fault engine: classify hypotheses
    9. Risk engine: estimate failure probability
    10. Degradation engine: update trends
    11. Assemble DiagnosticResult
    12. Return result (publishing handled by caller)
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.telemetry_processor = TelemetryProcessor(settings)
        self.baseline_engine = BaselineEngine(settings)
        self.anomaly_engine = AnomalyEngine(settings, self.baseline_engine)
        self.health_engine = HealthEngine(settings)
        self.fault_engine = FaultEngine(settings)
        self.risk_engine = RiskEngine(settings)
        self.degradation_engine = DegradationEngine(settings)

        # Equipment registry
        self._equipment: dict[str, Equipment] = {}
        self._last_results: dict[str, DiagnosticResult] = {}

    def register_equipment(self, equipment: Equipment) -> None:
        """Register an equipment asset for diagnostics."""
        self._equipment[equipment.equipment_id] = equipment
        # Create default baseline if none exists
        if self.baseline_engine.get_baseline(equipment.equipment_id) is None:
            self.baseline_engine.create_default_baseline(
                equipment.equipment_id, equipment.type,
            )

    def run_diagnostic(
        self,
        equipment_id: str,
        station_id: str,
        telemetry_batch: list[dict[str, Any]],
    ) -> DiagnosticResult:
        """
        Run the full 12-step diagnostic pipeline for an equipment asset.

        Args:
            equipment_id: Target equipment identifier
            station_id: Station identifier
            telemetry_batch: List of {signal_name, timestamp, value, unit?, quality?}
        """
        now = datetime.now(timezone.utc)

        # 1. Load equipment config
        equipment = self._equipment.get(equipment_id)
        if equipment is None:
            equipment = Equipment(
                equipment_id=equipment_id,
                station_id=station_id,
                type=EquipmentType.CUSTOM,
            )

        adapter = _get_adapter(equipment.type, self.settings)

        # 2. Telemetry processor: validate → clean → align
        window = self.telemetry_processor.ingest_batch(
            equipment_id=equipment_id,
            station_id=station_id,
            readings=telemetry_batch,
        )

        # Determine data quality from telemetry
        telem_quality = self.telemetry_processor.get_data_quality(equipment_id)
        data_quality = DataQuality(telem_quality) if telem_quality in [e.value for e in DataQuality] else DataQuality.GOOD

        # 3. Baseline engine: load expected behavior
        baseline = self.baseline_engine.get_baseline(equipment_id)

        # 4. Equipment adapter: extract features
        features = adapter.extract_features(window, baseline)

        # 5. Equipment adapter: rule checks
        rule_result = adapter.check_rules(window, equipment, baseline)

        # 6. Anomaly engine: 5-layer detection
        anomalies = self.anomaly_engine.detect_anomalies(
            window=window,
            equipment=equipment,
            features=features,
            rule_anomalies=rule_result.anomalies,
        )

        # Compute average residual magnitude for health scoring
        residual_magnitude = 0.0
        residual_anomalies = [a for a in anomalies if a.residual is not None]
        if residual_anomalies and baseline:
            residuals = []
            for a in residual_anomalies:
                if a.expected_value and abs(a.expected_value) > 1e-6:
                    residuals.append(abs(a.residual / a.expected_value))
            if residuals:
                residual_magnitude = sum(residuals) / len(residuals)

        # 7. Health engine: compute score
        degradation_rate = self.degradation_engine.get_overall_degradation_rate(equipment_id)
        health = self.health_engine.compute_health(
            equipment_id=equipment_id,
            station_id=station_id,
            anomalies=anomalies,
            residual_magnitude=residual_magnitude,
            degradation_rate=degradation_rate,
            last_maintenance=equipment.last_service_at,
            data_quality=data_quality,
        )

        # 8. Fault engine: classify hypotheses
        fault_report = self.fault_engine.classify_faults(
            equipment_id=equipment_id,
            station_id=station_id,
            anomalies=anomalies,
            features=features,
            adapter=adapter,
            window=window,
            data_quality=data_quality,
        )

        # 9. Risk engine: estimate failure probability
        failure_risk = self.risk_engine.estimate_risk(
            equipment_id=equipment_id,
            station_id=station_id,
            health_score=health.health_score,
            anomalies=anomalies,
            degradation_rate=degradation_rate,
            data_quality=data_quality,
        )

        # 10. Degradation engine: update trends
        self.degradation_engine.record_metric(equipment_id, "health_score", health.health_score)
        degradation_trends = self.degradation_engine.get_all_trends(equipment_id)
        degradation_info = {
            name: {
                "direction": trend.trend_direction,
                "rate_per_month": trend.degradation_rate_per_month,
                "confidence": trend.confidence,
            }
            for name, trend in degradation_trends.items()
        }

        # 11. Assemble recommendations
        recommendations: list[str] = []
        for fh in fault_report.hypotheses:
            if fh.confidence > 0.3 and fh.recommended_investigation:
                recommendations.append(fh.recommended_investigation)
        if rule_result.warnings:
            recommendations.extend(rule_result.warnings)
        if not recommendations:
            recommendations.append("No investigation required at this time.")

        # 12. Build DiagnosticResult
        result = DiagnosticResult(
            equipment_id=equipment_id,
            station_id=station_id,
            timestamp=now,
            health_score=health.health_score,
            health_state=health.health_state,
            anomaly_detected=len(anomalies) > 0,
            anomalies=anomalies,
            fault_hypotheses=fault_report.hypotheses,
            failure_risk=failure_risk,
            degradation=degradation_info,
            data_quality=data_quality,
            recommended_investigation=recommendations,
        )

        self._last_results[equipment_id] = result
        return result

    def get_latest_result(self, equipment_id: str) -> DiagnosticResult | None:
        """Get the most recent diagnostic result for an equipment."""
        return self._last_results.get(equipment_id)

    def get_equipment(self, equipment_id: str) -> Equipment | None:
        """Get registered equipment."""
        return self._equipment.get(equipment_id)

    def get_all_equipment_ids(self) -> list[str]:
        """List all registered equipment IDs."""
        return list(self._equipment.keys())

    def get_station_health_summary(self, station_id: str) -> dict[str, Any]:
        """Get aggregated health summary for a station."""
        station_equipment = [
            (eid, eq) for eid, eq in self._equipment.items()
            if eq.station_id == station_id
        ]

        total = len(station_equipment)
        healthy = 0
        degraded = 0
        at_risk = 0
        critical = 0
        unknown = 0
        scores: list[float] = []

        for eid, eq in station_equipment:
            result = self._last_results.get(eid)
            if result is None:
                unknown += 1
                continue

            scores.append(result.health_score)
            if result.health_state == HealthState.HEALTHY:
                healthy += 1
            elif result.health_state == HealthState.MONITORED:
                healthy += 1  # Count monitored as healthy for summary
            elif result.health_state == HealthState.DEGRADED:
                degraded += 1
            elif result.health_state == HealthState.AT_RISK:
                at_risk += 1
            elif result.health_state == HealthState.CRITICAL:
                critical += 1
            else:
                unknown += 1

        avg_health = sum(scores) / len(scores) if scores else 0.0

        return {
            "station_id": station_id,
            "total_equipment": total,
            "healthy": healthy,
            "degraded": degraded,
            "at_risk": at_risk,
            "critical": critical,
            "unknown": unknown,
            "average_health_score": round(avg_health, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
