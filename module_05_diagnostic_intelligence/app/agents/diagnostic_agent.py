"""
Frost OS Module 05 — Diagnostic Agent.

Coordination and interpretation layer. Selects relevant diagnostic models,
correlates anomalies across related equipment, and generates human-readable
diagnostic explanations.

MUST NOT directly shut down, derate, or command equipment.
Emergency protection belongs to deterministic safety systems / M07.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.diagnostic_engine import DiagnosticEngine, DiagnosticResult
from app.events.publisher import DiagnosticEventPublisher, DiagnosticEventType
from app.models.anomaly import AnomalySeverity
from app.models.equipment import EquipmentType
from app.models.health import HealthState

logger = structlog.get_logger(__name__)


class DiagnosticAgent:
    """
    High-level diagnostic coordination agent.

    Responsibilities:
    - Select relevant diagnostic models based on equipment type
    - Correlate anomalies across related equipment
    - Generate human-readable diagnostic explanations
    - Publish diagnostic events
    - Provide M01/M06/M07 interface responses

    Boundaries:
    - MUST NOT shut down, derate, or command equipment
    - MUST NOT override M07 safety decisions
    - Recommendations are informational only
    """

    def __init__(
        self,
        engine: DiagnosticEngine,
        publisher: DiagnosticEventPublisher | None = None,
    ) -> None:
        self.engine = engine
        self.publisher = publisher

    async def analyze_equipment(
        self,
        equipment_id: str,
        station_id: str,
        telemetry: list[dict[str, Any]],
    ) -> DiagnosticResult:
        """
        Run full diagnostic analysis on an equipment asset.

        Processes telemetry, detects anomalies, estimates health,
        classifies faults, and publishes events.
        """
        result = self.engine.run_diagnostic(equipment_id, station_id, telemetry)

        # Publish events if anomalies detected
        if self.publisher and result.anomaly_detected:
            equipment = self.engine.get_equipment(equipment_id)
            eq_type = equipment.type.value if equipment else ""

            # Publish anomaly event
            await self.publisher.publish_anomaly(
                station_id=station_id,
                equipment_id=equipment_id,
                equipment_type=eq_type,
                anomaly_data={
                    "anomaly_count": len(result.anomalies),
                    "health_score": result.health_score,
                    "health_state": result.health_state.value,
                    "top_anomalies": [
                        {
                            "type": a.type.value,
                            "severity": a.severity.value,
                            "score": a.score,
                            "signals": a.signals,
                        }
                        for a in result.anomalies[:3]
                    ],
                },
            )

            # Publish health change if degraded
            if result.health_state in (HealthState.DEGRADED, HealthState.AT_RISK, HealthState.CRITICAL):
                await self.publisher.publish_health_change(
                    station_id=station_id,
                    equipment_id=equipment_id,
                    health_data={
                        "health_score": result.health_score,
                        "health_state": result.health_state.value,
                        "anomaly_count": len(result.anomalies),
                    },
                )

            # Publish failure risk if elevated
            if result.failure_risk:
                risk_level = result.failure_risk.overall_risk_level.value
                if risk_level in ("MODERATE", "HIGH", "CRITICAL"):
                    await self.publisher.publish_failure_risk(
                        station_id=station_id,
                        equipment_id=equipment_id,
                        risk_data=result.failure_risk.model_dump(mode="json"),
                    )

        return result

    async def get_station_health(self, station_id: str) -> dict[str, Any]:
        """Get station-wide health summary for M01 orchestrator."""
        summary = self.engine.get_station_health_summary(station_id)

        # Add active alerts
        alerts: list[dict[str, Any]] = []
        for eid in self.engine.get_all_equipment_ids():
            result = self.engine.get_latest_result(eid)
            if result and result.anomaly_detected:
                for a in result.anomalies:
                    if a.severity in (AnomalySeverity.HIGH, AnomalySeverity.CRITICAL):
                        alerts.append({
                            "equipment_id": eid,
                            "severity": a.severity.value,
                            "type": a.type.value,
                            "signals": a.signals,
                            "timestamp": a.timestamp.isoformat(),
                        })

        summary["active_alerts"] = alerts
        return summary

    async def diagnose_for_m01(
        self,
        station_id: str,
        event_data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Handle M01 orchestrator diagnostic request.

        Returns equipment diagnostics in the format M01 expects.
        """
        equipment_id = event_data.get("equipment_id", "")

        if equipment_id:
            result = self.engine.get_latest_result(equipment_id)
        else:
            # Return station-level summary
            return await self.get_station_health(station_id)

        if result is None:
            return {
                "station_id": station_id,
                "equipment_id": equipment_id,
                "status": "no_diagnostic_data",
                "message": "No diagnostic data available for this equipment",
            }

        # Format for M01 compatibility
        issues = []
        for a in result.anomalies:
            issues.append({
                "issue_id": a.anomaly_id,
                "type": a.type.value,
                "severity": a.severity.value,
                "description": ", ".join(a.possible_causes[:2]) if a.possible_causes else "anomaly detected",
                "estimated_efficiency_loss_pct": abs(a.residual / a.expected_value * 100)
                    if a.residual and a.expected_value and abs(a.expected_value) > 0.01 else 0.0,
                "recommended_action": result.recommended_investigation[0] if result.recommended_investigation else "",
            })

        return {
            "station_id": station_id,
            "diagnostics": {
                "equipment_id": equipment_id,
                "equipment_type": (
                    self.engine.get_equipment(equipment_id).type.value
                    if self.engine.get_equipment(equipment_id) else "unknown"
                ),
                "status": result.health_state.value.lower(),
                "issues": issues,
                "overall_health_score": result.health_score / 100.0,
                "maintenance_recommended": result.health_state in (
                    HealthState.DEGRADED, HealthState.AT_RISK, HealthState.CRITICAL
                ),
                "estimated_repair_hours": 2.0 if issues else 0.0,
            },
        }

    async def get_equipment_capability_for_m06(
        self,
        equipment_id: str,
    ) -> dict[str, Any]:
        """
        Provide equipment availability/capability for M06 optimization.

        M06 decides allocation; M05 only describes capability/risk.
        """
        result = self.engine.get_latest_result(equipment_id)
        equipment = self.engine.get_equipment(equipment_id)

        if result is None or equipment is None:
            return {
                "equipment_id": equipment_id,
                "available_capacity_kw": None,
                "derated_capacity_kw": None,
                "equipment_health": "UNKNOWN",
                "operational_limit": None,
                "failure_risk": "UNKNOWN",
            }

        # Compute derating based on health
        rated_kw = equipment.rated_power_kw or 0.0
        derate_factor = min(1.0, result.health_score / 100.0)
        derated_kw = rated_kw * derate_factor

        risk_level = (
            result.failure_risk.overall_risk_level.value
            if result.failure_risk else "UNKNOWN"
        )

        return {
            "equipment_id": equipment_id,
            "available_capacity_kw": rated_kw,
            "derated_capacity_kw": round(derated_kw, 1),
            "equipment_health": result.health_state.value,
            "health_score": result.health_score,
            "operational_limit": derated_kw,
            "failure_risk": risk_level,
        }

    def explain_diagnostic(self, equipment_id: str) -> str:
        """Generate human-readable diagnostic explanation."""
        result = self.engine.get_latest_result(equipment_id)
        if result is None:
            return f"No diagnostic data available for equipment {equipment_id}."

        lines = [
            f"═══ Diagnostic Report: {equipment_id} ═══",
            f"Health Score: {result.health_score:.0f}/100 ({result.health_state.value})",
            f"Data Quality: {result.data_quality.value}",
            f"Anomalies Detected: {len(result.anomalies)}",
        ]

        if result.anomalies:
            lines.append("\nActive Anomalies:")
            for i, a in enumerate(result.anomalies[:5], 1):
                lines.append(
                    f"  {i}. [{a.severity.value}] {a.type.value} "
                    f"on {', '.join(a.signals)} "
                    f"(score={a.score:.2f}, confidence={a.confidence:.2f})"
                )

        if result.fault_hypotheses:
            lines.append("\nFault Hypotheses:")
            for fh in result.fault_hypotheses[:3]:
                lines.append(
                    f"  • {fh.fault} (confidence={fh.confidence:.2f})"
                    f"\n    Evidence: {', '.join(fh.evidence[:3])}"
                )

        if result.failure_risk:
            lines.append(f"\nFailure Risk: {result.failure_risk.overall_risk_level.value}")

        if result.recommended_investigation:
            lines.append("\nRecommended Investigation:")
            for r in result.recommended_investigation[:3]:
                lines.append(f"  → {r}")

        lines.append(f"\n[Module 05 — Informational only. Does NOT control equipment.]")

        return "\n".join(lines)
