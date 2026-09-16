"""
Frost OS Module 03 — End-to-End Integration Tests.

Validates complete workflow:
Telemetry Ingestion -> 13-step Processing -> DB Storage -> Redis Streams
-> Alerting -> Module 01 Orchestrator Inter-Module Contracts.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.events.publisher import EnergyEventPublisher
from app.models.telemetry import TelemetryRecord


@pytest.mark.asyncio
async def test_end_to_end_telemetry_flow_and_m01_contracts(
    client: AsyncClient,
    sample_telemetry_batch: list[TelemetryRecord],
    publisher: EnergyEventPublisher,
):
    """
    Test complete lifecycle from telemetry ingestion to Module 01 contract verification.
    """
    # 1. Ingest baseline polar batch
    payload = {"records": [r.model_dump(mode="json") for r in sample_telemetry_batch]}
    resp_ingest = await client.post("/api/v1/telemetry", json=payload)
    assert resp_ingest.status_code == 200

    # 2. Verify Redis Stream event was published
    assert len(publisher.published_events) > 0
    state_event = publisher.published_events[0]
    assert state_event.event_type.value in ("ENERGY_STATE_UPDATED", "DEFICIT_DETECTED")
    assert state_event.payload["net_power_kw"] == -40.0

    # 3. Test Module 01 Contract: GET /energy/station/{station_id}/status
    resp_m01_status = await client.get("/energy/station/halley_vi/status")
    assert resp_m01_status.status_code == 200
    m01_data = resp_m01_status.json()

    # Assert exact Module 01 client contract keys
    assert "station_id" in m01_data
    assert "generation" in m01_data
    assert "consumption" in m01_data
    assert "storage" in m01_data
    assert "grid_status" in m01_data

    gen = m01_data["generation"]
    assert gen["solar_kw"] == 120.0
    assert gen["wind_kw"] == 180.0
    assert gen["total_generation_kw"] == 300.0

    cons = m01_data["consumption"]
    assert cons["total_demand_kw"] == 340.0
    assert cons["deficit_kw"] == 40.0

    stor = m01_data["storage"]
    assert stor["battery_soc_pct"] == 72.0
    assert m01_data["grid_status"] == "deficit"

    # 4. Test Module 01 Contract: POST /energy/station/{station_id}/analyze
    # Simulate a sudden wind loss event sent by Module 01
    event_payload = {
        "event_id": "EVT-TEST-GEN-DROP",
        "event_type": "GENERATION_DROP",
        "station_id": "halley_vi",
        "timestamp": "2026-09-16T12:00:00Z",
        "payload": {
            "current_generation_kw": 70.0,
            "previous_generation_kw": 180.0,
        },
    }
    resp_analyze = await client.post("/energy/station/halley_vi/analyze", json=event_payload)
    assert resp_analyze.status_code == 200
    analyze_data = resp_analyze.json()

    assert "analysis" in analyze_data
    ana = analyze_data["analysis"]
    assert ana["current_generation_kw"] == 70.0
    assert ana["drop_kw"] > 0
    assert "requires_load_adjustment" in ana
    assert "battery_runway_hours" in ana


@pytest.mark.asyncio
async def test_anomaly_injection_and_alert_lifecycle(client: AsyncClient):
    """
    Test simulating an anomaly, triggering alerts, and acknowledging them.
    """
    # 1. Trigger simulation tick with generation_drop anomaly
    resp_sim = await client.post(
        "/api/v1/energy/simulate/halley_vi",
        json={"anomaly": "generation_drop"},
    )
    assert resp_sim.status_code == 200
    sim_data = resp_sim.json()
    assert sim_data["energy_state"] is not None

    # 2. Query alerts
    resp_alerts = await client.get("/api/v1/energy/alerts/halley_vi")
    assert resp_alerts.status_code == 200
    alerts = resp_alerts.json()
    # At least one alert should be present if thresholds triggered
    if alerts:
        target_alert = alerts[0]
        alert_id = target_alert["alert_id"]

        # 3. Acknowledge alert
        resp_ack = await client.post(f"/api/v1/energy/alerts/{alert_id}/acknowledge")
        assert resp_ack.status_code == 200
        assert resp_ack.json()["acknowledged"] is True
