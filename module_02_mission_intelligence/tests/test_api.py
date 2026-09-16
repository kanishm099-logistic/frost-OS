"""
Frost OS Module 02 — API Route Tests.

Tests all REST endpoints, CRUD operations, lifecycle commands,
and integration interfaces for Module 01 and Module 06.
"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestHealthAndStatus:
    """Test health check and module status."""

    async def test_health_returns_200(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    async def test_status_returns_200(self, client):
        resp = await client.get("/mission-intelligence/status?station_id=TEST-STATION-ALPHA")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "operational"
        assert data["station_id"] == "TEST-STATION-ALPHA"
        assert "active_missions" in data


@pytest.mark.asyncio
class TestMissionCRUD:
    """Test mission creation, retrieval, updates, and deletion."""

    async def test_create_mission_auto_classify(self, client):
        payload = {
            "station_id": "TEST-STATION-ALPHA",
            "name": "Atmospheric Radar Sounding",
            "description": "High altitude weather radar sweep for Katabatic wind detection",
            "required_power_kw": 30.0,
            "expected_duration_minutes": 120,
        }
        resp = await client.post("/missions", json=payload)
        assert resp.status_code == 201
        data = resp.json()["mission"]
        assert data["name"] == "Atmospheric Radar Sounding"
        assert data["type"] == "WEATHER_MONITORING"
        assert data["priority"] == "P1"
        assert data["energy_required_kwh"] == 60.0  # 30 kW * 2h
        assert data["buffer_kwh"] == 18.0          # +30% P1 buffer
        assert data["protected_energy_kwh"] == 78.0

    async def test_create_mission_explicit_values(self, client):
        payload = {
            "station_id": "TEST-STATION-ALPHA",
            "name": "Custom Research Lab",
            "description": "General laboratory analysis",
            "type": "LABORATORY",
            "priority": "P2",
            "required_power_kw": 20.0,
            "min_power_kw": 15.0,
            "max_power_kw": 25.0,
            "expected_duration_minutes": 60,
            "flexibility": "FLEXIBLE",
        }
        resp = await client.post("/missions", json=payload)
        assert resp.status_code == 201
        data = resp.json()["mission"]
        assert data["min_power_kw"] == 15.0
        assert data["max_power_kw"] == 25.0
        assert data["buffer_kwh"] == 3.0  # +15% P2 buffer on 20 kWh

    async def test_get_and_list_missions(self, client):
        # Create a mission
        resp_create = await client.post(
            "/missions",
            json={
                "station_id": "TEST-STATION-ALPHA",
                "name": "Listing Test Mission",
                "required_power_kw": 10.0,
                "expected_duration_minutes": 30,
            },
        )
        m_id = resp_create.json()["mission"]["mission_id"]

        # Get by ID
        resp_get = await client.get(f"/missions/{m_id}")
        assert resp_get.status_code == 200
        assert resp_get.json()["mission"]["mission_id"] == m_id

        # List all
        resp_list = await client.get("/missions")
        assert resp_list.status_code == 200
        assert resp_list.json()["total"] >= 1

    async def test_patch_mission(self, client):
        resp_create = await client.post(
            "/missions",
            json={
                "station_id": "TEST-STATION-ALPHA",
                "name": "Patch Target",
                "required_power_kw": 10.0,
                "expected_duration_minutes": 30,
            },
        )
        m_id = resp_create.json()["mission"]["mission_id"]

        # Patch name and power
        resp_patch = await client.patch(
            f"/missions/{m_id}",
            json={"name": "Patched Name", "required_power_kw": 15.0},
        )
        assert resp_patch.status_code == 200
        data = resp_patch.json()["mission"]
        assert data["name"] == "Patched Name"
        assert data["required_power_kw"] == 15.0
        assert data["energy_required_kwh"] == 7.5  # 15 kW * 0.5h

    async def test_delete_mission(self, client):
        resp_create = await client.post(
            "/missions",
            json={
                "station_id": "TEST-STATION-ALPHA",
                "name": "Delete Target",
                "required_power_kw": 10.0,
                "expected_duration_minutes": 30,
            },
        )
        m_id = resp_create.json()["mission"]["mission_id"]

        resp_del = await client.delete(f"/missions/{m_id}")
        assert resp_del.status_code == 204

        resp_get = await client.get(f"/missions/{m_id}")
        assert resp_get.status_code == 404


@pytest.mark.asyncio
class TestMissionOperations:
    """Test profile generation, energy query, priority query, and lifecycle."""

    async def test_generate_profile(self, client):
        resp_create = await client.post(
            "/missions",
            json={
                "station_id": "TEST-STATION-ALPHA",
                "name": "Ice Core Profile Test",
                "description": "Ice core spectrometry",
                "required_power_kw": 120.0,
                "min_power_kw": 90.0,
                "max_power_kw": 150.0,
                "expected_duration_minutes": 240,
            },
        )
        m_id = resp_create.json()["mission"]["mission_id"]

        resp_profile = await client.post(f"/missions/{m_id}/profile")
        assert resp_profile.status_code == 200
        p_data = resp_profile.json()["profile"]
        assert p_data["required_power_kw"] == 120.0
        assert p_data["min_power_kw"] == 90.0
        assert p_data["energy_required_kwh"] == 480.0
        assert p_data["buffer_kwh"] == 144.0
        assert p_data["protected_energy_kwh"] == 624.0
        assert "explanation" in resp_profile.json()

    async def test_lifecycle_transitions(self, client):
        resp_create = await client.post(
            "/missions",
            json={
                "station_id": "TEST-STATION-ALPHA",
                "name": "Lifecycle Workload",
                "required_power_kw": 25.0,
                "expected_duration_minutes": 60,
            },
        )
        m_id = resp_create.json()["mission"]["mission_id"]

        # START -> from CREATED is invalid according to state machine
        # (must be READY/SCHEDULED first)
        resp_bad_start = await client.post(f"/missions/{m_id}/start")
        assert resp_bad_start.status_code == 400

        # Patch state to READY
        resp_patch = await client.patch(f"/missions/{m_id}", json={"status": "READY"})
        assert resp_patch.status_code == 200
        assert resp_patch.json()["mission"]["status"] == "READY"

        # Now START is valid
        resp_start = await client.post(f"/missions/{m_id}/start", json={"reason": "Dispatch authorized"})
        assert resp_start.status_code == 200
        assert resp_start.json()["mission"]["status"] == "RUNNING"

        # PAUSE
        resp_pause = await client.post(f"/missions/{m_id}/pause", json={"reason": "Temporary load relief"})
        assert resp_pause.status_code == 200
        assert resp_pause.json()["mission"]["status"] == "PAUSED"

        # RESUME (START)
        resp_resume = await client.post(f"/missions/{m_id}/start", json={"reason": "Power restored"})
        assert resp_resume.status_code == 200
        assert resp_resume.json()["mission"]["status"] == "RUNNING"

        # COMPLETE
        resp_comp = await client.post(f"/missions/{m_id}/complete", json={"reason": "Job finished"})
        assert resp_comp.status_code == 200
        assert resp_comp.json()["mission"]["status"] == "COMPLETED"


@pytest.mark.asyncio
class TestModuleIntegrationEndpoints:
    """Test compatibility routes for Module 01 and Module 06."""

    async def test_m01_active_missions(self, client):
        # Create an active mission
        resp_create = await client.post(
            "/missions",
            json={
                "station_id": "TEST-STATION-ALPHA",
                "name": "Active Radar",
                "required_power_kw": 30.0,
                "min_power_kw": 20.0,
                "expected_duration_minutes": 60,
            },
        )
        m_id = resp_create.json()["mission"]["mission_id"]

        # Set status to READY so it counts as active
        # We can update status via db session directly in conftest or let's verify endpoint
        resp = await client.get("/missions/station/TEST-STATION-ALPHA/active")
        assert resp.status_code == 200
        data = resp.json()
        assert data["module_name"] == "mission"
        assert data["status"] == "success"
        assert "active_missions" in data["data"]

    async def test_m01_impact_analysis(self, client):
        # Create an active mission
        await client.post(
            "/missions",
            json={
                "station_id": "TEST-STATION-ALPHA",
                "name": "P0 Heat Test",
                "description": "Habitat heating",
                "type": "HEATING",
                "priority": "P0",
                "required_power_kw": 40.0,
                "min_power_kw": 30.0,
                "expected_duration_minutes": 120,
            },
        )

        impact_payload = {
            "station_id": "TEST-STATION-ALPHA",
            "payload": {
                "previous_kw": 200.0,
                "current_kw": 80.0,
            },
        }
        resp = await client.post(
            "/missions/station/TEST-STATION-ALPHA/impact-analysis",
            json=impact_payload,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["module_name"] == "mission"
        assert "impact_assessment" in data["data"]
        assert "recommendations" in data["data"]["impact_assessment"]

    async def test_m06_active_profiles(self, client):
        resp = await client.get("/missions/profiles/active?station_id=TEST-STATION-ALPHA")
        assert resp.status_code == 200
        data = resp.json()
        assert "profiles" in data
        assert "total_active_profiles" in data
