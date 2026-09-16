"""
Frost OS Module 04 — Operational Scenario Engine Tests.
"""

from __future__ import annotations

import pytest

from app.core.forecast_engine import ForecastEngine
from app.core.scenario_engine import ScenarioEngine
from app.data.historical_loader import HistoricalDataLoader
from app.data.nwp_adapter import MockNWPProvider
from app.models.scenario import ScenarioType


@pytest.mark.asyncio
async def test_all_9_operational_scenarios():
    """Verify that all 9 required operational scenarios generate valid results."""
    loader = HistoricalDataLoader()
    nwp_provider = MockNWPProvider()
    engine = ForecastEngine()
    scenario_engine = ScenarioEngine()

    history = loader.generate_synthetic_history(hours=48, season="summer")
    nwp = await nwp_provider.fetch_forecast("station", -75.58, -26.66, horizon_hours=12)
    base_run = engine.generate_forecast(nwp_records=nwp, history_df=history, horizon_hours=12)

    all_scenarios = [
        ScenarioType.BASELINE,
        ScenarioType.LOW_RENEWABLE,
        ScenarioType.HIGH_RENEWABLE,
        ScenarioType.HIGH_LOAD,
        ScenarioType.LOW_WIND,
        ScenarioType.SOLAR_DROP,
        ScenarioType.STORM,
        ScenarioType.EQUIPMENT_DEGRADATION,
        ScenarioType.COMMUNICATION_LOSS,
    ]

    for st in all_scenarios:
        res = scenario_engine.generate_scenario(scenario_type=st, base_records=base_run.records)
        assert res.scenario_type == st
        assert len(res.records) > 0
        assert res.min_battery_soc_pct >= 0.0
        assert res.projected_shortage_kwh >= 0.0

    # Specific Scenario Validation:
    # 1. STORM shuts down wind turbines completely (feathering)
    storm_res = scenario_engine.generate_scenario(
        ScenarioType.STORM, base_records=base_run.records
    )
    storm_wind_records = [r for r in storm_res.records if r.target.value == "wind_generation_kw"]
    for r in storm_wind_records:
        assert r.prediction == 0.0

    # 2. HIGH_LOAD increases demand
    load_res = scenario_engine.generate_scenario(
        ScenarioType.HIGH_LOAD, base_records=base_run.records
    )
    high_loads = [r.prediction for r in load_res.records if r.target.value == "station_load_kw"]
    base_loads = [r.prediction for r in base_run.records if r.target.value == "station_load_kw"]
    assert sum(high_loads) > sum(base_loads)

    # 3. COMMUNICATION_LOSS widens prediction interval width
    comm_res = scenario_engine.generate_scenario(
        ScenarioType.COMMUNICATION_LOSS, base_records=base_run.records
    )
    comm_solar = [r for r in comm_res.records if r.target.value == "solar_generation_kw"]
    base_solar = [r for r in base_run.records if r.target.value == "solar_generation_kw"]
    assert (comm_solar[0].upper_bound - comm_solar[0].lower_bound) >= (base_solar[0].upper_bound - base_solar[0].lower_bound)
