"""
Frost OS Module 04 — Polar Simulation & Operational Demonstration.

Demonstrates:
1. Austral Summer (Polar Day): 24h continuous low solar elevation + wind supply.
2. Austral Winter (Polar Night): 0.0 kW solar baseline, reliance on wind and storage.
3. Wind Collapse Event: Sudden katabatic lull causes wind generation drop, declining trend,
   and elevated energy-deficit risk advisory for M01/M06/M07.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.agents.forecast_agent import ForecastAgent
from app.config.settings import get_settings
from app.core.forecast_engine import ForecastEngine
from app.core.risk_engine import RiskEngine
from app.core.scenario_engine import ScenarioEngine
from app.data.historical_loader import HistoricalDataLoader
from app.data.nwp_adapter import MockNWPProvider
from app.models.forecast import ForecastTarget
from app.models.scenario import ScenarioType


async def run_polar_demo() -> None:
    print("=" * 80)
    print(" FROST OS — MODULE 04: FORECAST INTELLIGENCE DEMONSTRATION")
    print("=" * 80)

    settings = get_settings()
    loader = HistoricalDataLoader(settings.station_id, settings.latitude, settings.longitude)
    nwp_provider = MockNWPProvider()
    engine = ForecastEngine(
        station_id=settings.station_id,
        solar_capacity_kw=settings.solar_installed_capacity_kw,
        wind_capacity_kw=settings.wind_installed_capacity_kw,
        battery_capacity_kwh=settings.battery_capacity_kwh,
        hydrogen_capacity_kwh=settings.hydrogen_capacity_kwh,
        base_load_kw=settings.base_station_load_kw,
        latitude=settings.latitude,
        longitude=settings.longitude,
    )
    risk_engine = RiskEngine(
        battery_min_soc_pct=settings.battery_min_soc_pct,
        hydrogen_min_level_pct=settings.hydrogen_min_level_pct,
    )
    scenario_engine = ScenarioEngine(
        station_id=settings.station_id,
        solar_capacity_kw=settings.solar_installed_capacity_kw,
        wind_capacity_kw=settings.wind_installed_capacity_kw,
    )
    agent = ForecastAgent(settings.station_id)

    # ──────────────────────────────────────────────────────────────────
    # CASE 1: AUSTRAL SUMMER (POLAR DAY)
    # ──────────────────────────────────────────────────────────────────
    print("\n[CASE 1] AUSTRAL SUMMER (POLAR DAY) - 72-Hour Historical Baseline")
    summer_now = datetime(2026, 12, 21, 12, 0, tzinfo=timezone.utc)
    summer_history = loader.generate_synthetic_history(hours=72, season="summer", end_time=summer_now)
    summer_nwp = await nwp_provider.fetch_forecast(
        settings.station_id, settings.latitude, settings.longitude, horizon_hours=24, issue_time=summer_now
    )
    summer_run = engine.generate_forecast(
        nwp_records=summer_nwp,
        history_df=summer_history,
        horizon_hours=24,
        creation_time=summer_now,
    )

    solar_pts = [r for r in summer_run.records if r.target == ForecastTarget.SOLAR_GENERATION_KW]
    wind_pts = [r for r in summer_run.records if r.target == ForecastTarget.WIND_GENERATION_KW]
    load_pts = [r for r in summer_run.records if r.target == ForecastTarget.STATION_LOAD_KW]

    mean_solar = sum(r.prediction for r in solar_pts) / len(solar_pts)
    mean_wind = sum(r.prediction for r in wind_pts) / len(wind_pts)
    mean_load = sum(r.prediction for r in load_pts) / len(load_pts)

    print(f" -> Station: {settings.station_id} (Lat: {settings.latitude} deg, Lon: {settings.longitude} deg)")
    print(f" -> Mean Solar PV Output: {mean_solar:.1f} kW (Continuous daylight diurnal cycle)")
    print(f" -> Mean Wind Output:     {mean_wind:.1f} kW")
    print(f" -> Mean Station Demand:  {mean_load:.1f} kW")
    print(f" -> Net Power Balance:    {mean_solar + mean_wind - mean_load:+.1f} kW")

    # ──────────────────────────────────────────────────────────────────
    # CASE 2: AUSTRAL WINTER (POLAR NIGHT)
    # ──────────────────────────────────────────────────────────────────
    print("\n[CASE 2] AUSTRAL WINTER (POLAR NIGHT) - Zero Solar Irradiance")
    winter_now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    winter_history = loader.generate_synthetic_history(hours=72, season="winter", end_time=winter_now)
    winter_nwp = await nwp_provider.fetch_forecast(
        settings.station_id, settings.latitude, settings.longitude, horizon_hours=24, issue_time=winter_now, weather_event="POLAR_NIGHT"
    )
    winter_run = engine.generate_forecast(
        nwp_records=winter_nwp,
        history_df=winter_history,
        horizon_hours=24,
        creation_time=winter_now,
    )

    w_solar_pts = [r for r in winter_run.records if r.target == ForecastTarget.SOLAR_GENERATION_KW]
    max_w_solar = max(r.prediction for r in w_solar_pts)
    print(f" -> Max Winter Solar Forecast: {max_w_solar:.1f} kW (Physical elevation cutoff strictly enforced)")

    # ──────────────────────────────────────────────────────────────────
    # CASE 3: WIND COLLAPSE EVENT & ENERGY DEFICIT RISK ADVISORY
    # ──────────────────────────────────────────────────────────────────
    print("\n[CASE 3] SYNOPTIC WIND COLLAPSE — Transition to Severe Energy Deficit")
    collapse_history = loader.generate_synthetic_history(
        hours=72, season="winter", include_wind_collapse=True
    )
    collapse_nwp = await nwp_provider.fetch_forecast(
        settings.station_id, settings.latitude, settings.longitude, horizon_hours=24, weather_event="WIND_COLLAPSE"
    )
    collapse_run = engine.generate_forecast(
        nwp_records=collapse_nwp,
        history_df=collapse_history,
        horizon_hours=24,
    )

    c_risks, c_shortage = risk_engine.evaluate_risks(
        station_id=settings.station_id,
        forecast_records=collapse_run.records,
        current_battery_soc_pct=50.0,
    )
    c_explanation = agent.explain_forecast_summary(collapse_run, c_risks, c_shortage)

    print(f" -> Generation Trend:       {c_explanation['trend'].upper()}")
    print(f" -> Active Risks Detected:  {len(c_risks)}")
    for r in c_risks:
        print(f"    * [{r.risk_level.value}] {r.risk_type.value}: {r.impact_description}")
        print(f"      Advisory: {r.recommended_advisory}")

    print(f" -> Energy Shortage Risk:   {c_shortage.has_shortage_risk}")
    print(f" -> Expected Shortage:      {c_shortage.expected_shortage_kwh:.1f} kWh (Prob: {c_shortage.shortage_probability * 100:.1f}%)")
    print(f" -> Worst-Case Shortage:    {c_shortage.worst_case_shortage_kwh:.1f} kWh")
    print(f" -> First Risk Time:        {c_shortage.first_risk_time}")

    # ──────────────────────────────────────────────────────────────────
    # CASE 4: OPERATIONAL SCENARIOS (STORM & LOW RENEWABLE)
    # ──────────────────────────────────────────────────────────────────
    print("\n[CASE 4] OPERATIONAL WHAT-IF SCENARIOS (M06/M07 ADVISORY INPUTS)")
    storm_result = scenario_engine.generate_scenario(
        scenario_type=ScenarioType.STORM,
        base_records=collapse_run.records,
    )
    print(f" -> Scenario: {storm_result.scenario_type.value}")
    print(f"    Description: {storm_result.description}")
    print(f"    Projected Shortage: {storm_result.projected_shortage_kwh:.1f} kWh")
    print(f"    Min Battery SOC:    {storm_result.min_battery_soc_pct:.1f}%")

    print("\n" + "=" * 80)
    print(" DEMONSTRATION COMPLETE: Module 04 fulfills pure advisory role.")
    print(" (Zero hardware control dispatched; M06 and M07 handle decision and safety).")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_polar_demo())
