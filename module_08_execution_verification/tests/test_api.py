"""
Integration tests for Module 08 REST API Endpoints.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    """Test GET /health"""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["service"] == "Module 08 Execution + Verification Intelligence"


def test_status_endpoint():
    """Test GET /execution/status"""
    response = client.get("/execution/status")
    assert response.status_code == 200
    data = response.json()
    assert data["station_id"] == "POLAR-STATION-ALPHA"
    assert data["registered_devices_count"] >= 5


def test_list_devices_endpoint():
    """Test GET /devices"""
    response = client.get("/devices")
    assert response.status_code == 200
    data = response.json()
    assert "devices" in data
    assert len(data["devices"]) >= 5


def test_get_device_capabilities():
    """Test GET /devices/BAT-01/capabilities"""
    response = client.get("/devices/BAT-01/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["device_id"] == "BAT-01"
    assert "capabilities" in data


def test_execute_plan_endpoint_authorized():
    """Test POST /execution/plans/PLAN-API-001/execute with valid authorized plan."""
    payload = {
        "plan": {
            "plan_id": "PLAN-API-001",
            "station_id": "POLAR-STATION-ALPHA",
            "authorization_id": "AUTH-API-999",
            "safety_validation_id": "VAL-SAFE-API-888",
            "status": "SAFE",
            "actions": [
                {
                    "action_id": "ACT-API-01",
                    "plan_id": "PLAN-API-001",
                    "station_id": "POLAR-STATION-ALPHA",
                    "action_type": "DISCHARGE_BATTERY",
                    "target_id": "BAT-01",
                    "sequence": 1,
                    "parameters": {"power_kw": 50.0},
                }
            ],
        },
        "idempotency_key": "IDEMP-API-KEY-001",
    }

    response = client.post("/execution/plans/PLAN-API-001/execute", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "COMPLETED"
    assert "execution_id" in data
