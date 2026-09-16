"""
Frost OS Module 04 — End-to-End Pipeline Integration Tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.forecast_engine import ForecastEngine
from app.core.risk_engine import RiskEngine
from app.data.historical_loader import HistoricalDataLoader
from app.data.nwp_adapter import MockNWPProvider
from app.events.publisher import ForecastEventPublisher, ForecastEventType
from app.models.forecast import ForecastTarget
from app.storage.repository import ForecastRepository, RiskRepository


@pytest.mark.asyncio
async def test_end_to_end_forecasting_pipeline(test_db_session: AsyncSession):
    """
    Verify complete pipeline from historical telemetry -> NWP -> Models ->
    Uncertainty -> Risk Engine -> Database Persistence -> Redis Event.
    """
    station = "polar-station-alpha"
    loader = HistoricalDataLoader(station_id=station)
    nwp_provider = MockNWPProvider()
    engine = ForecastEngine(station_id=station)
    risk_engine = RiskEngine()
    publisher = ForecastEventPublisher()

    # 1. Historical data
    history = loader.generate_synthetic_history(hours=72, season="summer")
    assert len(history) > 0

    # 2. NWP forecast
    raw_nwp = await nwp_provider.fetch_forecast(station, -75.58, -26.66, horizon_hours=24)
    nwp = nwp_provider.downscale_and_correct(raw_nwp, station_altitude_m=30.0)
    assert len(nwp) == 24

    # 3. Forecast generation
    run = engine.generate_forecast(
        nwp_records=nwp,
        history_df=history,
        current_energy_state={"battery_soc_pct": 80.0, "hydrogen_level_pct": 75.0},
        horizon_hours=24,
    )
    assert len(run.records) == 24 * 10  # 10 targets per hour

    # 4. Risk assessment
    risks, shortage = risk_engine.evaluate_risks(
        station_id=station,
        forecast_records=run.records,
        current_battery_soc_pct=80.0,
    )

    # 5. Database persistence
    forecast_repo = ForecastRepository(test_db_session)
    await forecast_repo.save_forecast_run(run)

    risk_repo = RiskRepository(test_db_session)
    await risk_repo.save_risks(risks)

    # Verify retrieval
    loaded_run, loaded_records = await forecast_repo.get_run(run.run_id)
    assert loaded_run is not None
    assert len(loaded_records) == len(run.records)

    # 6. Event publishing
    await publisher.publish_event(
        ForecastEventType.FORECAST_UPDATED,
        station_id=station,
        payload={"run_id": run.run_id, "record_count": len(run.records)},
    )
    published = publisher.get_published_events()
    assert len(published) == 1
    assert published[0]["event_type"] == ForecastEventType.FORECAST_UPDATED.value
    assert published[0]["station_id"] == station
