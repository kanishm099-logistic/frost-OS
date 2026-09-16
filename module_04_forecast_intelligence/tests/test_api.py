"""
Frost OS Module 04 — API Endpoint Integration Tests.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_health_and_status_endpoints(async_client: httpx.AsyncClient):
    """Verify health check and service status endpoints."""
    res_health = await async_client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    res_status = await async_client.get("/forecast-intelligence/status")
    assert res_status.status_code == 200
    data = res_status.json()
    assert data["status"] == "OPERATIONAL"
    assert data["models_active"] >= 3


@pytest.mark.asyncio
async def test_forecast_generate_and_retrieval(async_client: httpx.AsyncClient):
    """Verify generating on-demand forecast and retrieving details."""
    payload = {
        "station_id": "polar-station-alpha",
        "horizon_hours": 24,
        "current_energy_state": {"battery_soc_pct": 82.0, "hydrogen_level_pct": 78.0},
    }
    res_gen = await async_client.post("/forecasts/generate", json=payload)
    assert res_gen.status_code == 201
    data_gen = res_gen.json()
    assert data_gen["success"] is True
    assert data_gen["record_count"] > 0
    run_id = data_gen["run_id"]

    # List runs
    res_list = await async_client.get("/forecasts?station_id=polar-station-alpha")
    assert res_list.status_code == 200
    assert any(r["run_id"] == run_id for r in res_list.json())

    # Get specific run
    res_run = await async_client.get(f"/forecasts/{run_id}")
    assert res_run.status_code == 200
    assert len(res_run.json()["records"]) == data_gen["record_count"]


@pytest.mark.asyncio
async def test_target_specific_station_endpoints(async_client: httpx.AsyncClient):
    """Verify target-specific endpoints for generation, load, storage, and risk."""
    station = "polar-station-alpha"

    # Generation
    res_gen = await async_client.get(f"/forecasts/stations/{station}/generation")
    assert res_gen.status_code == 200
    assert res_gen.json()["target_category"] == "renewable_generation"

    # Load
    res_load = await async_client.get(f"/forecasts/stations/{station}/load")
    assert res_load.status_code == 200
    assert res_load.json()["target_category"] == "station_load"

    # Storage
    res_store = await async_client.get(f"/forecasts/stations/{station}/storage")
    assert res_store.status_code == 200
    assert res_store.json()["target_category"] == "storage_trajectories"

    # Risk
    res_risk = await async_client.get(f"/forecasts/stations/{station}/risk")
    assert res_risk.status_code == 200
    assert "risks" in res_risk.json()


@pytest.mark.asyncio
async def test_scenarios_and_models_endpoints(async_client: httpx.AsyncClient):
    """Verify scenario generation and model lifecycle endpoints."""
    # Scenarios
    scen_req = {
        "station_id": "polar-station-alpha",
        "scenarios": ["BASELINE", "LOW_WIND", "STORM"],
    }
    res_scen = await async_client.post("/forecasts/scenarios", json=scen_req)
    assert res_scen.status_code == 200
    assert len(res_scen.json()["results"]) == 3

    # Models
    res_models = await async_client.get("/models")
    assert res_models.status_code == 200
    assert len(res_models.json()) >= 3

    res_model_detail = await async_client.get("/models/wind_v0.1")
    assert res_model_detail.status_code == 200
    assert res_model_detail.json()["model_name"] == "wind_v0.1"

    # Train
    res_train = await async_client.post("/models/wind_v0.1/train", json={"hours_history": 48})
    assert res_train.status_code == 200
    assert res_train.json()["status"] == "success"

    # Validate
    res_val = await async_client.post("/models/wind_v0.1/validate", json={"test_split": 0.2})
    assert res_val.status_code == 200
    assert res_val.json()["validation_passed"] is True


@pytest.mark.asyncio
async def test_module_01_compatibility_contracts(async_client: httpx.AsyncClient):
    """
    Verify strict backward compatibility with Module 01 ForecastClient contract:
    - /forecast/station/{station_id}?hours=24
    - /forecast/station/{station_id}/weather
    """
    station = "polar-station-alpha"

    # 1. Generation forecast contract
    res_f = await async_client.get(f"/forecast/station/{station}?hours=24")
    assert res_f.status_code == 200
    data_f = res_f.json()
    assert data_f["station_id"] == station
    assert data_f["forecast_hours"] == 24
    assert len(data_f["wind_forecast"]) > 0
    assert len(data_f["solar_forecast"]) > 0
    assert data_f["trend"] in ["stable", "declining", "increasing"]
    assert "lowest_generation_kw" in data_f
    assert "recovery_expected_hour" in data_f
    assert 0.0 <= data_f["confidence"] <= 1.0

    # 2. Weather forecast contract
    res_w = await async_client.get(f"/forecast/station/{station}/weather")
    assert res_w.status_code == 200
    data_w = res_w.json()
    assert data_w["station_id"] == station
    assert "temperature_c" in data_w
    assert "wind_speed_ms" in data_w
    assert "icing_risk" in data_w
    assert "storm_warning" in data_w
