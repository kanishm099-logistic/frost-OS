"""
Integration tests for Module 06 FastAPI endpoints.
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
    assert data["service"] == "Module 06 Optimization Intelligence"


def test_status_endpoint():
    """Test GET /optimization/status"""
    response = client.get("/optimization/status")
    assert response.status_code == 200
    data = response.json()
    assert "station_id" in data
    assert "default_solver" in data


def test_run_optimization_endpoint():
    """Test POST /optimization/run"""
    response = client.post("/optimization/run")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "optimization_id" in data
    assert "result" in data


def test_scenarios_endpoint():
    """Test POST /optimization/scenarios"""
    response = client.post("/optimization/scenarios")
    assert response.status_code == 200
    data = response.json()
    assert "scenarios_evaluated" in data
    assert len(data["scenarios_evaluated"]) > 0
