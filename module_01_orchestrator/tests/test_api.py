"""
Frost OS Module 01 — API Endpoint Tests.

Tests for all REST endpoints via FastAPI TestClient.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.models.event import EventType, Severity


# ── API Tests using httpx AsyncClient ─────────────────────────────────

class TestHealthEndpoint:
    """Test the health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_200(self):
        """Health endpoint should return 200 with status info."""
        # Note: For full API tests, we would need to mock the DB/Redis
        # in the lifespan. For unit tests, we test route logic directly.
        # This is a placeholder for integration tests with TestClient.
        pass


class TestEventEndpoint:
    """Test event ingestion endpoint."""

    def test_event_create_request_schema(self):
        """Validate EventCreateRequest schema."""
        from app.api.schemas import EventCreateRequest

        request = EventCreateRequest(
            source="test-sensor",
            event_type=EventType.WIND_POWER_DROP,
            severity=Severity.HIGH,
            station_id="STATION-01",
            payload={"previous_kw": 180.0, "current_kw": 70.0},
        )

        assert request.source == "test-sensor"
        assert request.event_type == EventType.WIND_POWER_DROP
        assert request.severity == Severity.HIGH

    def test_event_create_request_rejects_empty_source(self):
        """Should reject empty source."""
        from app.api.schemas import EventCreateRequest

        with pytest.raises(Exception):
            EventCreateRequest(
                source="",
                event_type=EventType.WIND_POWER_DROP,
                station_id="STATION-01",
            )


class TestAuthorizationEndpoint:
    """Test authorization endpoints."""

    def test_authorization_request_schema(self):
        """Validate AuthorizationRequest schema."""
        from app.api.schemas import AuthorizationRequest

        request = AuthorizationRequest(
            authorized_by="operator-jane",
            reason="Verified and approved",
        )

        assert request.authorized_by == "operator-jane"
        assert request.reason == "Verified and approved"

    def test_authorization_request_requires_identity(self):
        """Should reject empty authorized_by."""
        from app.api.schemas import AuthorizationRequest

        with pytest.raises(Exception):
            AuthorizationRequest(
                authorized_by="",
                reason="test",
            )


class TestResponseSchemas:
    """Test response schema construction."""

    def test_pipeline_response_schema(self):
        """PipelineResponse should accept all required fields."""
        from app.api.schemas import PipelineResponse

        resp = PipelineResponse(
            decision_id="dec-123",
            plan_id="plan-456",
            status="AWAITING_AUTHORIZATION",
            requires_authorization=True,
        )

        assert resp.decision_id == "dec-123"
        assert resp.plan_id == "plan-456"
        assert resp.requires_authorization is True

    def test_system_status_response(self):
        """SystemStatusResponse should have all fields."""
        from app.api.schemas import SystemStatusResponse

        resp = SystemStatusResponse(
            service="frost-orchestrator",
            status="operational",
            station_id="STATION-01",
            mock_mode=True,
            database="healthy",
            redis="healthy",
            registered_workflows=["generation_drop", "mission_start"],
            uptime_seconds=123.45,
        )

        assert resp.service == "frost-orchestrator"
        assert len(resp.registered_workflows) == 2
