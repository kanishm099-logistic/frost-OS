"""
Frost OS Module 05 — API Integration Tests.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    """Create test client with full app lifecycle (lifespan triggered)."""
    from app.main import create_app
    app = create_app()

    # Manually trigger lifespan so app.state is populated
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


class TestAPIEndpoints:
    """Tests for REST API endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """GET /api/v1/health should return service status."""
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "frost-diagnostic-intelligence"
        assert data["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_analyze_equipment(self, client):
        """POST /api/v1/diagnostics/analyze should process telemetry."""
        payload = {
            "equipment_id": "WT-001",
            "station_id": "FROST-STATION-ALPHA",
            "readings": [
                {"signal_name": "power_kw", "value": 50.0},
                {"signal_name": "wind_speed_ms", "value": 8.0},
                {"signal_name": "vibration", "value": 2.0},
            ],
        }
        resp = await client.post("/api/v1/diagnostics/analyze", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "diagnostic_id" in data
        assert "health_score" in data
        assert "anomaly_detected" in data
        assert "data_quality" in data

    @pytest.mark.asyncio
    async def test_get_latest_diagnostic(self, client):
        """GET /api/v1/diagnostics/{equipment_id} after analyze."""
        # First, run analysis
        await client.post("/api/v1/diagnostics/analyze", json={
            "equipment_id": "WT-001",
            "readings": [
                {"signal_name": "power_kw", "value": 50.0},
            ],
        })

        resp = await client.get("/api/v1/diagnostics/WT-001")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_get_nonexistent_diagnostic_404(self, client):
        """GET /api/v1/diagnostics/{unknown} should return 404."""
        resp = await client.get("/api/v1/diagnostics/DOES-NOT-EXIST")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_register_equipment(self, client):
        """POST /api/v1/equipment/register should create equipment."""
        payload = {
            "equipment_id": "PUMP-TEST-001",
            "station_id": "FROST-STATION-ALPHA",
            "equipment_type": "PUMP",
        }
        resp = await client.post("/api/v1/equipment/register", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "registered"

    @pytest.mark.asyncio
    async def test_list_equipment(self, client):
        """GET /api/v1/equipment should list registered equipment."""
        resp = await client.get("/api/v1/equipment")
        assert resp.status_code == 200
        data = resp.json()
        assert "equipment_count" in data
        assert data["equipment_count"] >= 1  # Demo equipment

    @pytest.mark.asyncio
    async def test_explain_diagnostic(self, client):
        """GET /api/v1/diagnostics/{id}/explain should return text."""
        await client.post("/api/v1/diagnostics/analyze", json={
            "equipment_id": "WT-001",
            "readings": [
                {"signal_name": "power_kw", "value": 50.0},
            ],
        })

        resp = await client.get("/api/v1/diagnostics/WT-001/explain")
        assert resp.status_code == 200
        data = resp.json()
        assert "explanation" in data
        assert "Module 05" in data["explanation"]

    @pytest.mark.asyncio
    async def test_m01_diagnose_endpoint(self, client):
        """POST /api/v1/diagnostics/m01/diagnose should return M01 format."""
        await client.post("/api/v1/diagnostics/analyze", json={
            "equipment_id": "WT-001",
            "readings": [
                {"signal_name": "power_kw", "value": 50.0},
            ],
        })

        resp = await client.post("/api/v1/diagnostics/m01/diagnose", json={
            "equipment_id": "WT-001",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "diagnostics" in data

    @pytest.mark.asyncio
    async def test_equipment_capability(self, client):
        """GET /api/v1/equipment/{id}/capability should return M06 format."""
        await client.post("/api/v1/diagnostics/analyze", json={
            "equipment_id": "WT-001",
            "readings": [
                {"signal_name": "power_kw", "value": 50.0},
            ],
        })

        resp = await client.get("/api/v1/equipment/WT-001/capability")
        assert resp.status_code == 200
        data = resp.json()
        assert "derated_capacity_kw" in data
        assert "failure_risk" in data

    @pytest.mark.asyncio
    async def test_recent_events(self, client):
        """GET /api/v1/events/recent should list events."""
        resp = await client.get("/api/v1/events/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert "event_count" in data
