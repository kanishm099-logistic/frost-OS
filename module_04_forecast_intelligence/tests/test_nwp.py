"""
Frost OS Module 04 — NWP Adapter & Downscaling Tests.
"""

from __future__ import annotations

import pytest

from app.data.nwp_adapter import MockNWPProvider, get_nwp_adapter


@pytest.mark.asyncio
async def test_mock_nwp_provider_fetch():
    """Verify mock NWP generation generates 72 hourly records with physical ranges."""
    provider = MockNWPProvider()
    records = await provider.fetch_forecast(
        station_id="polar-station-alpha",
        latitude=-75.58,
        longitude=-26.66,
        horizon_hours=72,
    )
    assert len(records) == 72
    for r in records:
        assert -60.0 <= r.temperature_c <= 10.0
        assert 0.0 <= r.wind_speed_ms <= 40.0
        assert 0.0 <= r.cloud_cover_pct <= 100.0
        assert r.solar_radiation_wm2 >= 0.0


@pytest.mark.asyncio
async def test_nwp_downscaling_and_corrections():
    """Verify physical downscaling applies altitude and roughness adjustments."""
    provider = MockNWPProvider()
    raw = await provider.fetch_forecast(
        station_id="polar-station-alpha",
        latitude=-75.58,
        longitude=-26.66,
        horizon_hours=6,
    )
    downscaled = provider.downscale_and_correct(
        raw, station_altitude_m=500.0, temperature_bias_c=1.0, wind_speed_bias_ms=0.5
    )
    assert len(downscaled) == 6
    # With 500m altitude and 1.0C warm bias, downscaled temperature should be lower than raw
    for r, d in zip(raw, downscaled):
        assert d.temperature_c < r.temperature_c
        assert d.wind_speed_ms <= r.wind_speed_ms
        assert "Downscaled" in d.model_name


@pytest.mark.asyncio
async def test_nwp_weather_events():
    """Verify simulated event modifications (STORM, WIND_COLLAPSE, SOLAR_DROP)."""
    provider = MockNWPProvider()

    # Storm event
    storm_recs = await provider.fetch_forecast(
        "station", -75.58, -26.66, horizon_hours=12, weather_event="STORM"
    )
    max_wind = max(r.wind_speed_ms for r in storm_recs)
    assert max_wind > 24.0  # Katabatic storm speeds

    # Wind collapse
    collapse_recs = await provider.fetch_forecast(
        "station", -75.58, -26.66, horizon_hours=24, weather_event="WIND_COLLAPSE"
    )
    late_wind = [r.wind_speed_ms for r in collapse_recs if r.lead_time_hours >= 12]
    assert min(late_wind) < 4.0

    # Solar drop
    solar_drop_recs = await provider.fetch_forecast(
        "station", -75.58, -26.66, horizon_hours=12, weather_event="SOLAR_DROP"
    )
    for r in solar_drop_recs:
        assert r.cloud_cover_pct >= 95.0


def test_nwp_adapter_factory():
    """Verify adapter factory returns correct instances."""
    mock = get_nwp_adapter("mock")
    assert isinstance(mock, MockNWPProvider)
    ecmwf = get_nwp_adapter("ecmwf")
    assert ecmwf is not None
    noaa = get_nwp_adapter("noaa")
    assert noaa is not None
