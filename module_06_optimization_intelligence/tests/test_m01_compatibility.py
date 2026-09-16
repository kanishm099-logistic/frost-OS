"""
Unit and integration tests for Module 01 Orchestrator compatibility endpoints in Module 06.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_m01_optimize_compat_endpoint_default():
    """Test POST /optimizer/station/{station_id}/optimize with default context."""
    station_id = "POLAR-STATION-ALPHA"
    response = client.post(f"/optimizer/station/{station_id}/optimize", json={})
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["status"] == "success"
    assert data["module_name"] == "optimizer"

    res_data = data["data"]
    assert res_data["station_id"] == station_id
    assert "optimization_result" in res_data

    opt_result = res_data["optimization_result"]
    assert "strategy" in opt_result
    assert "actions" in opt_result
    assert isinstance(opt_result["actions"], list)
    assert len(opt_result["actions"]) > 0
    assert "projected_balance_kw" in opt_result
    assert "projected_reserve_kwh" in opt_result
    assert "confidence" in opt_result


def test_m01_optimize_compat_endpoint_with_context():
    """Test POST /optimizer/station/{station_id}/optimize with realistic event context."""
    station_id = "POLAR-STATION-ALPHA"
    context = {
        "event_type": "GENERATION_DROP",
        "current_generation_kw": 25.0,
        "required_load_kw": 60.0,
        "battery_soc_pct": 65.0,
    }

    response = client.post(f"/optimizer/station/{station_id}/optimize", json=context)
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["status"] == "success"
    assert data["module_name"] == "optimizer"

    actions = data["data"]["optimization_result"]["actions"]
    assert len(actions) > 0

    # Ensure each action has required schema fields
    for action in actions:
        assert "action_type" in action
        assert "target" in action
        assert "description" in action
        assert "priority" in action
        assert "reversible" in action


def test_m01_optimize_compat_alias_route():
    """Test POST /optimization/station/{station_id}/optimize alias path."""
    station_id = "POLAR-STATION-BETA"
    response = client.post(f"/optimization/station/{station_id}/optimize", json={})
    assert response.status_code == 200, response.text

    data = response.json()
    assert data["status"] == "success"
    assert data["data"]["station_id"] == station_id
