"""
Frost OS Module 04 — Energy Risk & Shortage Assessment Engine.

Computes probabilistic risk metrics across forecast distributions and intervals:
- LOW_RENEWABLE_RISK
- ENERGY_DEFICIT_RISK
- BATTERY_LOW_RISK
- HYDROGEN_DEPLETION_RISK
- HIGH_LOAD_RISK
- WIND_COLLAPSE_RISK
- SOLAR_DROP_RISK

Produces structured advisory EnergyShortageAssessment for M06 Optimizer and M07 Safety.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.forecast import ForecastRecord, ForecastTarget
from app.models.risk import (
    EnergyShortageAssessment,
    ForecastRisk,
    RiskLevel,
    RiskType,
)


class RiskEngine:
    """Calculates distribution-based operational risks and shortage projections."""

    def __init__(
        self,
        battery_min_soc_pct: float = 15.0,
        hydrogen_min_level_pct: float = 10.0,
        high_load_threshold_kw: float = 65.0,
    ) -> None:
        self.battery_min_soc_pct = battery_min_soc_pct
        self.hydrogen_min_level_pct = hydrogen_min_level_pct
        self.high_load_threshold_kw = high_load_threshold_kw

    def evaluate_risks(
        self,
        station_id: str,
        forecast_records: list[ForecastRecord],
        current_battery_soc_pct: float = 80.0,
        current_hydrogen_pct: float = 75.0,
    ) -> tuple[list[ForecastRisk], EnergyShortageAssessment]:
        """
        Evaluate full forecast run for operational risk events and overall shortage assessment.
        """
        now = datetime.now(timezone.utc)
        risks: list[ForecastRisk] = []

        # Index records by target and timestamp
        by_target: dict[ForecastTarget, list[ForecastRecord]] = {}
        for r in forecast_records:
            by_target.setdefault(r.target, []).append(r)

        for target in by_target:
            by_target[target].sort(key=lambda x: x.timestamp)

        wind_recs = by_target.get(ForecastTarget.WIND_GENERATION_KW, [])
        solar_recs = by_target.get(ForecastTarget.SOLAR_GENERATION_KW, [])
        load_recs = by_target.get(ForecastTarget.STATION_LOAD_KW, [])
        soc_recs = by_target.get(ForecastTarget.BATTERY_SOC_PCT, [])
        h2_recs = by_target.get(ForecastTarget.HYDROGEN_LEVEL_PCT, [])
        surplus_recs = by_target.get(ForecastTarget.ENERGY_SURPLUS_DEFICIT_KW, [])

        # 1. WIND_COLLAPSE_RISK: Detect sharp drop in wind generation
        if len(wind_recs) >= 2:
            initial_wind = wind_recs[0].prediction
            for i, rec in enumerate(wind_recs[1:], 1):
                # If wind drops by > 50% and lower bound reaches 0.0
                if initial_wind > 20.0 and rec.prediction < (initial_wind * 0.40):
                    lead_mins = rec.horizon_minutes
                    prob = 0.85 if rec.lower_bound <= 0.0 else 0.65
                    severity = RiskLevel.HIGH if rec.prediction < 10.0 else RiskLevel.MEDIUM
                    risks.append(
                        ForecastRisk(
                            station_id=station_id,
                            timestamp=now,
                            risk_type=RiskType.WIND_COLLAPSE_RISK,
                            risk_level=severity,
                            probability=round(prob, 2),
                            lead_time_minutes=lead_mins,
                            target_time=rec.timestamp,
                            impact_description=(
                                f"Projected wind generation collapse from {initial_wind:.1f} kW "
                                f"to {rec.prediction:.1f} kW within {lead_mins} minutes."
                            ),
                            recommended_advisory="Advise Module 06 to reserve BESS capacity and defer non-critical batch loads.",
                            details={"initial_kw": initial_wind, "projected_kw": rec.prediction},
                        )
                    )
                    break

        # 2. SOLAR_DROP_RISK: Detect sudden solar attenuation
        if len(solar_recs) >= 2:
            initial_solar = solar_recs[0].prediction
            for rec in solar_recs[1:]:
                if initial_solar > 25.0 and rec.prediction < 5.0 and rec.horizon_minutes <= 360:
                    lead_mins = rec.horizon_minutes
                    risks.append(
                        ForecastRisk(
                            station_id=station_id,
                            timestamp=now,
                            risk_type=RiskType.SOLAR_DROP_RISK,
                            risk_level=RiskLevel.MEDIUM,
                            probability=0.75,
                            lead_time_minutes=lead_mins,
                            target_time=rec.timestamp,
                            impact_description=f"Rapid solar generation drop from {initial_solar:.1f} kW to {rec.prediction:.1f} kW due to cloud cover.",
                            recommended_advisory="Advisory: Monitor wind generation and thermal storage reserves.",
                        )
                    )
                    break

        # 3. HIGH_LOAD_RISK: Detect peak demand exceeding threshold
        for rec in load_recs:
            if rec.upper_bound >= self.high_load_threshold_kw:
                lead_mins = rec.horizon_minutes
                sev = RiskLevel.CRITICAL if rec.prediction >= 75.0 else RiskLevel.HIGH
                risks.append(
                    ForecastRisk(
                        station_id=station_id,
                        timestamp=now,
                        risk_type=RiskType.HIGH_LOAD_RISK,
                        risk_level=sev,
                        probability=0.80 if rec.prediction >= self.high_load_threshold_kw else 0.55,
                        lead_time_minutes=lead_mins,
                        target_time=rec.timestamp,
                        impact_description=f"Predicted peak load {rec.prediction:.1f} kW (upper interval {rec.upper_bound:.1f} kW) exceeds baseline thresholds.",
                        recommended_advisory="Advise Module 06 to evaluate load shedding of flexible P3/P4 missions.",
                    )
                )
                break

        # 4. BATTERY_LOW_RISK: Projected SOC falling below safe reserve
        for rec in soc_recs:
            if rec.lower_bound <= self.battery_min_soc_pct + 5.0:
                lead_mins = rec.horizon_minutes
                sev = RiskLevel.CRITICAL if rec.prediction <= self.battery_min_soc_pct else RiskLevel.HIGH
                prob = 0.90 if rec.prediction <= self.battery_min_soc_pct else 0.60
                risks.append(
                    ForecastRisk(
                        station_id=station_id,
                        timestamp=now,
                        risk_type=RiskType.BATTERY_LOW_RISK,
                        risk_level=sev,
                        probability=round(prob, 2),
                        lead_time_minutes=lead_mins,
                        target_time=rec.timestamp,
                        impact_description=f"Projected battery SOC {rec.prediction:.1f}% (P10 bound {rec.lower_bound:.1f}%) breaches safety reserve {self.battery_min_soc_pct:.1f}%.",
                        recommended_advisory="Advise Module 07 to verify safety reserve and Module 06 to initiate load curtailment.",
                    )
                )
                break

        # 5. HYDROGEN_DEPLETION_RISK: H2 buffer depletion
        for rec in h2_recs:
            if rec.lower_bound <= self.hydrogen_min_level_pct:
                risks.append(
                    ForecastRisk(
                        station_id=station_id,
                        timestamp=now,
                        risk_type=RiskType.HYDROGEN_DEPLETION_RISK,
                        risk_level=RiskLevel.HIGH,
                        probability=0.70,
                        lead_time_minutes=rec.horizon_minutes,
                        target_time=rec.timestamp,
                        impact_description=f"Hydrogen fuel cell buffer projected to reach {rec.prediction:.1f}%, near critical threshold {self.hydrogen_min_level_pct}%.",
                        recommended_advisory="Advisory: Long-term reserve critically low. Prioritize P0 life support.",
                    )
                )
                break

        # 6. ENERGY_DEFICIT_RISK and SHORTAGE ASSESSMENT:
        expected_shortage_kwh = 0.0
        worst_case_shortage_kwh = 0.0
        peak_deficit_kw = 0.0
        first_risk_time: datetime | None = None
        deficit_steps = 0
        step_duration_minutes = 60  # default hourly

        # Correlate load and surplus/deficit
        for rec in surplus_recs:
            if rec.prediction < 0:
                deficit_kw = abs(rec.prediction)
                peak_deficit_kw = max(peak_deficit_kw, deficit_kw)
                expected_shortage_kwh += deficit_kw * 1.0  # 1 hour
                deficit_steps += 1
                if first_risk_time is None:
                    first_risk_time = rec.timestamp

            # Worst-case uses lower interval bound (most pessimistic net power)
            if rec.lower_bound < 0:
                worst_case_shortage_kwh += abs(rec.lower_bound) * 1.0

        risk_duration_minutes = deficit_steps * 60
        has_shortage = expected_shortage_kwh > 50.0 or worst_case_shortage_kwh > 100.0

        shortage_prob = 0.0
        if has_shortage:
            shortage_prob = min(0.95, round(0.40 + (expected_shortage_kwh / 500.0) * 0.55, 2))
            risks.append(
                ForecastRisk(
                    station_id=station_id,
                    timestamp=now,
                    risk_type=RiskType.ENERGY_DEFICIT_RISK,
                    risk_level=RiskLevel.HIGH if expected_shortage_kwh < 200 else RiskLevel.CRITICAL,
                    probability=shortage_prob,
                    lead_time_minutes=int((first_risk_time - now).total_seconds() / 60) if first_risk_time else 60,
                    target_time=first_risk_time or now,
                    impact_description=(
                        f"Cumulative projected energy deficit: {expected_shortage_kwh:.1f} kWh "
                        f"(worst case {worst_case_shortage_kwh:.1f} kWh) over {risk_duration_minutes} minutes."
                    ),
                    recommended_advisory="Advisory for M06/M07: Expected generation insufficient for projected load without storage depletion.",
                )
            )

        # Primary driver
        primary_driver = "NONE"
        if any(r.risk_type == RiskType.WIND_COLLAPSE_RISK for r in risks):
            primary_driver = "WIND_COLLAPSE"
        elif any(r.risk_type == RiskType.HIGH_LOAD_RISK for r in risks):
            primary_driver = "HIGH_LOAD_SPIKE"
        elif any(r.risk_type == RiskType.SOLAR_DROP_RISK for r in risks):
            primary_driver = "SOLAR_ATTENUATION"
        elif has_shortage:
            primary_driver = "PERSISTENT_GENERATION_DEFICIT"

        shortage_assessment = EnergyShortageAssessment(
            station_id=station_id,
            evaluation_time=now,
            horizon_hours=72,
            has_shortage_risk=has_shortage,
            expected_shortage_kwh=round(expected_shortage_kwh, 2),
            worst_case_shortage_kwh=round(worst_case_shortage_kwh, 2),
            shortage_probability=shortage_prob,
            first_risk_time=first_risk_time,
            risk_duration_minutes=risk_duration_minutes,
            peak_deficit_kw=round(peak_deficit_kw, 2),
            primary_driver=primary_driver,
            active_risks=risks,
        )

        return risks, shortage_assessment
