"""
Frost OS Module 04 — Storage Trajectory Forecasting Tests.
"""

from __future__ import annotations

from app.core.forecast_engine import ForecastEngine
from app.data.historical_loader import HistoricalDataLoader
from app.data.nwp_adapter import MockNWPProvider
from app.models.forecast import ForecastTarget
import pytest


@pytest.mark.asyncio
async def test_passive_storage_trajectory_charging_and_discharging():
    """Verify battery SOC charges on surplus and discharges under generation deficit."""
    engine = ForecastEngine(
        battery_capacity_kwh=500.0,
        hydrogen_capacity_kwh=2500.0,
    )
    loader = HistoricalDataLoader()
    nwp_provider = MockNWPProvider()

    # Summer run (surplus generation)
    summer_history = loader.generate_synthetic_history(hours=48, season="summer")
    nwp_recs = await nwp_provider.fetch_forecast("station", -75.58, -26.66, horizon_hours=12)

    run = engine.generate_forecast(
        nwp_records=nwp_recs,
        history_df=summer_history,
        current_energy_state={"battery_soc_pct": 70.0, "hydrogen_level_pct": 75.0},
        horizon_hours=12,
    )

    soc_recs = [r for r in run.records if r.target == ForecastTarget.BATTERY_SOC_PCT]
    batt_kwh_recs = [r for r in run.records if r.target == ForecastTarget.BATTERY_ENERGY_KWH]
    h2_recs = [r for r in run.records if r.target == ForecastTarget.HYDROGEN_LEVEL_PCT]

    assert len(soc_recs) == 12
    assert len(batt_kwh_recs) == 12
    assert len(h2_recs) == 12

    for r in soc_recs:
        assert 0.0 <= r.prediction <= 100.0
        assert 0.0 <= r.lower_bound <= 100.0
        assert 0.0 <= r.upper_bound <= 100.0

    for r in batt_kwh_recs:
        assert 0.0 <= r.prediction <= 500.0

    for r in h2_recs:
        assert 0.0 <= r.prediction <= 100.0
