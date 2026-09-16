"""
Frost OS Module 03 — REST API Endpoints Tests.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models.telemetry import TelemetryRecord


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    """Test health endpoint."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["module"] == "module_03_energy_intelligence"


@pytest.mark.asyncio
async def test_ingest_telemetry_and_retrieve_state(
    client: AsyncClient,
    sample_telemetry_batch: list[TelemetryRecord],
):
    """Test batch telemetry ingestion and subsequent state retrieval."""
    payload = {
        "records": [r.model_dump(mode="json") for r in sample_telemetry_batch]
    }
    # 1. Ingest batch
    resp = await client.post("/api/v1/telemetry", json=payload)
    assert resp.status_code == 200
    ingest_data = resp.json()
    assert ingest_data["processed_count"] == len(sample_telemetry_batch)
    assert ingest_data["station_id"] == "halley_vi"
    assert ingest_data["energy_state"] is not None

    # 2. Retrieve state
    resp_state = await client.get("/api/v1/energy/state/halley_vi")
    assert resp_state.status_code == 200
    state = resp_state.json()
    assert state["station_id"] == "halley_vi"
    assert state["generation"]["total_generation_kw"] == 300.0
    assert state["load"]["total_load_kw"] == 340.0
    assert state["net_power_kw"] == -40.0
    assert state["battery"]["soc_pct"] == 72.0


@pytest.mark.asyncio
async def test_breakdown_endpoints(
    client: AsyncClient,
    sample_telemetry_batch: list[TelemetryRecord],
):
    """Test generation, load, and storage breakdown endpoints."""
    # First ingest batch
    payload = {"records": [r.model_dump(mode="json") for r in sample_telemetry_batch]}
    await client.post("/api/v1/telemetry", json=payload)

    # Generation
    resp_gen = await client.get("/api/v1/energy/generation/halley_vi")
    assert resp_gen.status_code == 200
    gen_data = resp_gen.json()
    assert gen_data["solar_kw"] == 120.0
    assert gen_data["wind_kw"] == 180.0

    # Load
    resp_load = await client.get("/api/v1/energy/load/halley_vi")
    assert resp_load.status_code == 200
    load_data = resp_load.json()
    assert load_data["total_load_kw"] == 340.0
    assert load_data["critical_kw"] == 120.0

    # Storage
    resp_stor = await client.get("/api/v1/energy/storage/halley_vi")
    assert resp_stor.status_code == 200
    stor_data = resp_stor.json()
    assert stor_data["battery"]["soc_pct"] == 72.0
    assert stor_data["hydrogen"]["level_pct"] == 81.0


@pytest.mark.asyncio
async def test_agent_api_endpoints(
    client: AsyncClient,
    sample_telemetry_batch: list[TelemetryRecord],
):
    """Test natural language query and load evaluation endpoints."""
    payload = {"records": [r.model_dump(mode="json") for r in sample_telemetry_batch]}
    await client.post("/api/v1/telemetry", json=payload)

    # Query endpoint
    query_payload = {
        "station_id": "halley_vi",
        "question": "What is our current battery status?",
    }
    resp_query = await client.post("/api/v1/energy/query", json=query_payload)
    assert resp_query.status_code == 200
    q_data = resp_query.json()
    assert q_data["intent"] == "RUNWAY"
    assert "battery" in q_data["answer"].lower()

    # Evaluate load endpoint
    eval_payload = {
        "station_id": "halley_vi",
        "additional_kw": 25.0,
        "duration_hours": 1.5,
    }
    resp_eval = await client.post("/api/v1/energy/evaluate-load", json=eval_payload)
    assert resp_eval.status_code == 200
    eval_data = resp_eval.json()
    assert eval_data["feasible"] is True
    assert eval_data["verdict"] in ("FEASIBLE", "MARGINAL")


@pytest.mark.asyncio
async def test_simulate_endpoint(client: AsyncClient):
    """Test simulator trigger endpoint."""
    resp = await client.post("/api/v1/energy/simulate/halley_vi")
    assert resp.status_code == 200
    data = resp.json()
    assert data["station_id"] == "halley_vi"
    assert data["processed_count"] > 5
    assert data["energy_state"] is not None
