"""
Integration tests for Module 07 FastAPI REST Endpoints.
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
    assert data["service"] == "Module 07 Safety + Reserve Intelligence"


def test_status_endpoint():
    """Test GET /safety/status/POLAR-STATION-ALPHA"""
    response = client.get("/safety/status/POLAR-STATION-ALPHA")
    assert response.status_code == 200
    data = response.json()
    assert data["station_id"] == "POLAR-STATION-ALPHA"
    assert data["deterministic_mode"] is True
    assert data["llm_safety_decisions"] is False


def test_rules_endpoint():
    """Test GET /safety/rules"""
    response = client.get("/safety/rules")
    assert response.status_code == 200
    data = response.json()
    assert "rules" in data
    assert len(data["rules"]) >= 5


def test_policies_endpoint():
    """Test GET /safety/policies"""
    response = client.get("/safety/policies")
    assert response.status_code == 200
    data = response.json()
    assert "policy_version" in data
    assert "reserve_policy" in data


def test_validate_endpoint_safe_plan():
    """Test POST /safety/validate with standard safe plan."""
    payload = {
        "proposed_plan": {
            "optimization_id": "OPT-API-TEST-001",
            "total_load_kw": 80.0,
            "actions": [{"action_type": "MAINTAIN_DISPATCH", "target": "Microgrid"}],
            "mission_allocations": [
                {
                    "mission_id": "MIS-P0-LIFE",
                    "mission_name": "Life Support",
                    "priority": "P0",
                    "requested_power_kw": 40.0,
                    "allocated_power_kw": 40.0,
                    "min_power_kw": 40.0,
                    "satisfied": True,
                }
            ],
        }
    }

    response = client.post("/safety/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["status"] == "SAFE"
    assert "validation_id" in data


def test_simulate_scenario_endpoint():
    """Test POST /safety/simulate with STORM scenario."""
    payload = {
        "station_id": "POLAR-STATION-ALPHA",
        "scenario_name": "STORM",
    }

    response = client.post("/safety/simulate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["scenario"] == "STORM"
    assert "validation" in data
