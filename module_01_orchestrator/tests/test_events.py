"""
Frost OS Module 01 — Event Tests.

Tests for event validation, classification, routing, and idempotency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.event import EventType, Severity, StationEvent
from app.core.event_router import EventRouter, ROUTING_TABLE, RouteConfig


# ── Event Validation ──────────────────────────────────────────────────

class TestEventValidation:
    """Test StationEvent schema validation."""

    def test_valid_event_creation(self, wind_drop_event):
        """A well-formed event should be created successfully."""
        assert wind_drop_event.event_id is not None
        assert wind_drop_event.event_type == EventType.WIND_POWER_DROP
        assert wind_drop_event.severity == Severity.HIGH
        assert wind_drop_event.station_id == "TEST-STATION-01"
        assert wind_drop_event.payload["previous_kw"] == 180.0

    def test_event_requires_source(self):
        """Source is mandatory and must be non-empty."""
        with pytest.raises(Exception):
            StationEvent(
                source="",
                event_type=EventType.WIND_POWER_DROP,
                station_id="STATION-01",
            )

    def test_event_requires_station_id(self):
        """Station ID is mandatory."""
        with pytest.raises(Exception):
            StationEvent(
                source="sensor-01",
                event_type=EventType.WIND_POWER_DROP,
                station_id="",
            )

    def test_event_auto_generates_ids(self):
        """Event should auto-generate event_id and correlation_id."""
        event = StationEvent(
            source="sensor-01",
            event_type=EventType.BATTERY_LOW,
            station_id="STATION-01",
        )
        assert event.event_id is not None
        assert event.correlation_id is not None
        assert len(event.event_id) == 36  # UUID format

    def test_event_auto_generates_timestamp(self):
        """Event should auto-generate a UTC timestamp."""
        event = StationEvent(
            source="sensor-01",
            event_type=EventType.BATTERY_LOW,
            station_id="STATION-01",
        )
        assert event.timestamp is not None
        assert event.timestamp.tzinfo is not None

    def test_event_type_enum_validation(self):
        """Invalid event type should be rejected."""
        with pytest.raises(Exception):
            StationEvent(
                source="sensor-01",
                event_type="INVALID_EVENT",
                station_id="STATION-01",
            )

    def test_event_severity_defaults_to_medium(self):
        """Default severity should be MEDIUM."""
        event = StationEvent(
            source="sensor-01",
            event_type=EventType.MISSION_STARTED,
            station_id="STATION-01",
        )
        assert event.severity == Severity.MEDIUM

    def test_event_payload_defaults_to_empty(self):
        """Default payload should be empty dict."""
        event = StationEvent(
            source="sensor-01",
            event_type=EventType.BATTERY_LOW,
            station_id="STATION-01",
        )
        assert event.payload == {}


# ── Event Classification ──────────────────────────────────────────────

class TestEventClassification:
    """Test event classification via routing table."""

    def test_all_event_types_have_routes(self):
        """Every EventType enum member must have a routing entry."""
        for event_type in EventType:
            assert event_type in ROUTING_TABLE, f"Missing route for {event_type}"

    def test_wind_power_drop_classification(self, event_router, wind_drop_event):
        """WIND_POWER_DROP should route to generation_drop workflow."""
        route = event_router.classify(wind_drop_event)
        assert route.workflow_name == "generation_drop"
        assert "energy" in route.affected_modules
        assert "forecast" in route.affected_modules
        assert "diagnostic" in route.affected_modules

    def test_battery_low_classification(self, event_router, battery_low_event):
        """BATTERY_LOW should route to low_reserve workflow."""
        route = event_router.classify(battery_low_event)
        assert route.workflow_name == "low_reserve"
        assert "reserve" in route.affected_modules

    def test_mission_started_classification(self, event_router, mission_started_event):
        """MISSION_STARTED should route to mission_start workflow."""
        route = event_router.classify(mission_started_event)
        assert route.workflow_name == "mission_start"
        assert "mission" in route.affected_modules

    def test_equipment_degraded_classification(self, event_router, equipment_degraded_event):
        """EQUIPMENT_DEGRADED should route to equipment_failure workflow."""
        route = event_router.classify(equipment_degraded_event)
        assert route.workflow_name == "equipment_failure"
        assert "diagnostic" in route.affected_modules

    def test_weather_warning_classification(self, event_router, weather_warning_event):
        """WEATHER_WARNING should route to weather_risk workflow."""
        route = event_router.classify(weather_warning_event)
        assert route.workflow_name == "weather_risk"
        assert "forecast" in route.affected_modules


# ── Event Routing ─────────────────────────────────────────────────────

class TestEventRouting:
    """Test that event routing returns correct affected modules."""

    def test_wind_drop_routes_to_correct_modules(self, event_router, wind_drop_event):
        """WIND_POWER_DROP should invoke Energy, Forecast, Diagnostic, Mission, Optimizer, Reserve."""
        modules = event_router.get_affected_modules(wind_drop_event)
        expected = {"energy", "forecast", "diagnostic", "mission", "optimizer", "reserve"}
        assert set(modules) == expected

    def test_mission_started_routes_correctly(self, event_router, mission_started_event):
        """MISSION_STARTED should invoke Mission, Energy, Optimizer, Reserve."""
        modules = event_router.get_affected_modules(mission_started_event)
        expected = {"mission", "energy", "optimizer", "reserve"}
        assert set(modules) == expected

    def test_communication_loss_includes_diagnostic(self, event_router):
        """COMMUNICATION_LOSS should include diagnostic module."""
        event = StationEvent(
            source="comms-monitor",
            event_type=EventType.COMMUNICATION_LOSS,
            station_id="STATION-01",
        )
        modules = event_router.get_affected_modules(event)
        assert "diagnostic" in modules

    def test_get_all_routes_returns_complete_table(self, event_router):
        """get_all_routes should return entries for all event types."""
        routes = event_router.get_all_routes()
        assert len(routes) == len(EventType)
        for event_type in EventType:
            assert event_type.value in routes

    def test_severity_override(self, event_router):
        """Event's own non-MEDIUM severity should override table default."""
        event = StationEvent(
            source="sensor",
            event_type=EventType.SOLAR_OUTPUT_DROP,
            severity=Severity.CRITICAL,
            station_id="STATION-01",
        )
        severity = event_router.get_severity(event)
        assert severity == Severity.CRITICAL
