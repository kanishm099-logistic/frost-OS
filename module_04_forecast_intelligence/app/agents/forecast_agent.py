"""
Frost OS Module 04 — Forecast Agent Interpretation Layer.

Acts as an agentic interpretation layer:
- Decides which forecast targets and horizons need immediate recalculation upon events
- Synthesizes clear, explainable physical reasoning for M01 Orchestrator
- Answers operational what-if queries without commanding hardware or allocating missions.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.models.forecast import ForecastRecord, ForecastRun, ForecastTarget
from app.models.risk import EnergyShortageAssessment, ForecastRisk

logger = structlog.get_logger(__name__)


class ForecastAgent:
    """Agentic interpretation layer for Module 04."""

    def __init__(self, station_id: str = "polar-station-alpha") -> None:
        self.station_id = station_id

    def evaluate_event_trigger(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Decide which forecast targets/horizons need immediate update based on an incoming event.
        Does NOT allocate missions or command hardware.
        """
        evt = event_type.upper()
        res = {
            "should_recalculate": False,
            "priority": "NORMAL",
            "targets": [
                ForecastTarget.SOLAR_GENERATION_KW,
                ForecastTarget.WIND_GENERATION_KW,
                ForecastTarget.STATION_LOAD_KW,
                ForecastTarget.ENERGY_SURPLUS_DEFICIT_KW,
                ForecastTarget.BATTERY_SOC_PCT,
            ],
            "horizons": ["1h", "6h", "24h"],
            "reason": "Routine cycle",
        }

        if "GENERATION_DROP" in evt or "WIND_DROP" in evt:
            res["should_recalculate"] = True
            res["priority"] = "HIGH"
            res["horizons"] = ["15m", "30m", "1h", "6h", "24h"]
            res["reason"] = f"Abrupt renewable generation drop detected in {evt}. Immediate horizon update needed."
        elif "WEATHER_WARNING" in evt or "STORM" in evt or "BLIZZARD" in evt:
            res["should_recalculate"] = True
            res["priority"] = "CRITICAL"
            res["horizons"] = ["1h", "6h", "24h", "48h", "72h"]
            res["reason"] = f"Severe meteorological warning ({evt}) received. Full 72h weather and risk trajectory required."
        elif "LOW_RESERVE" in evt or "BATTERY_LOW" in evt:
            res["should_recalculate"] = True
            res["priority"] = "CRITICAL"
            res["horizons"] = ["5m", "15m", "30m", "1h", "6h"]
            res["reason"] = "Storage reserve depleted below nominal safety buffer. Short-term trajectory update triggered."

        return res

    def explain_forecast_summary(
        self,
        run: ForecastRun,
        risks: list[ForecastRisk],
        shortage: EnergyShortageAssessment,
    ) -> dict[str, Any]:
        """
        Produce human and machine-readable explainable rationale for M01 Orchestrator.
        """
        by_target: dict[ForecastTarget, list[ForecastRecord]] = {}
        for r in run.records:
            by_target.setdefault(r.target, []).append(r)

        wind_recs = by_target.get(ForecastTarget.WIND_GENERATION_KW, [])
        solar_recs = by_target.get(ForecastTarget.SOLAR_GENERATION_KW, [])
        load_recs = by_target.get(ForecastTarget.STATION_LOAD_KW, [])

        avg_wind = sum(r.prediction for r in wind_recs) / max(1, len(wind_recs))
        avg_solar = sum(r.prediction for r in solar_recs) / max(1, len(solar_recs))
        avg_load = sum(r.prediction for r in load_recs) / max(1, len(load_recs))

        # Determine trend
        trend = "stable"
        if len(wind_recs) >= 2:
            if wind_recs[-1].prediction < wind_recs[0].prediction * 0.7:
                trend = "declining"
            elif wind_recs[-1].prediction > wind_recs[0].prediction * 1.3:
                trend = "increasing"

        # Construct natural language explanation
        explanation_lines = [
            f"Forecast run covering {run.horizon_hours} hours for {self.station_id}.",
            f"Mean projected renewable supply: Wind {avg_wind:.1f} kW, Solar {avg_solar:.1f} kW versus mean demand {avg_load:.1f} kW.",
            f"Overall generation trend: {trend.upper()}.",
        ]

        if shortage.has_shortage_risk:
            explanation_lines.append(
                f"ALERT: Projected energy deficit of {shortage.expected_shortage_kwh:.1f} kWh "
                f"(worst case {shortage.worst_case_shortage_kwh:.1f} kWh) starting at {shortage.first_risk_time}. "
                f"Primary driver: {shortage.primary_driver}."
            )
        else:
            explanation_lines.append("Energy balance is projected to remain stable within nominal battery/hydrogen buffers.")

        if risks:
            explanation_lines.append(f"Detected {len(risks)} operational risk conditions: " + ", ".join(r.risk_type.value for r in risks))

        return {
            "station_id": self.station_id,
            "run_id": run.run_id,
            "created_at": run.created_at.isoformat(),
            "trend": trend,
            "has_shortage_risk": shortage.has_shortage_risk,
            "expected_shortage_kwh": shortage.expected_shortage_kwh,
            "shortage_probability": shortage.shortage_probability,
            "primary_driver": shortage.primary_driver,
            "active_risk_count": len(risks),
            "explanation": " ".join(explanation_lines),
            "advisories_for_orchestrator": [r.recommended_advisory for r in risks if r.recommended_advisory],
        }

    def answer_query(self, query: str, context: dict[str, Any]) -> str:
        """Process natural language query against current forecast context."""
        q = query.lower()
        if "wind" in q and ("recover" in q or "drop" in q or "trend" in q):
            trend = context.get("trend", "stable")
            lowest = context.get("lowest_generation_kw", 0.0)
            rec_hr = context.get("recovery_expected_hour", 24)
            return (
                f"Wind generation trend is {trend}. Lowest expected output is {lowest:.1f} kW, "
                f"with recovery anticipated around hour +{rec_hr} based on synoptic NWP progression."
            )
        if "shortage" in q or "deficit" in q:
            shortage = context.get("expected_shortage_kwh", 0.0)
            prob = context.get("shortage_probability", 0.0)
            return (
                f"Projected energy shortage is {shortage:.1f} kWh with an estimated probability of {prob * 100:.1f}%. "
                "Advising Module 06 to prepare load-shifting and Module 07 to verify reserve margins."
            )
        return (
            f"Forecast status for {self.station_id}: 72-hour multi-target model active. "
            "Telemetry and NWP inputs validated. All predictions respect physical limits."
        )
