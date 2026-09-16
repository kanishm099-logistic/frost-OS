"""
Frost OS Module 01 — Event Classification & Routing Table.

Data-driven mapping from EventType to severity, criticality,
affected modules, and workflow. No hardcoded if/else — pure
table lookup + registry pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from app.models.event import EventType, Severity, StationEvent

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RouteConfig:
    """Configuration for how a specific event type is routed."""
    default_severity: Severity
    criticality: str  # "low", "medium", "high", "critical"
    affected_modules: tuple[str, ...]
    workflow_name: str


# ── Routing Table ─────────────────────────────────────────────────────
# Pure data — no conditionals. Each EventType maps to exactly one route.

ROUTING_TABLE: dict[EventType, RouteConfig] = {
    EventType.WIND_POWER_DROP: RouteConfig(
        default_severity=Severity.HIGH,
        criticality="high",
        affected_modules=("energy", "forecast", "diagnostic", "mission", "optimizer", "reserve"),
        workflow_name="generation_drop",
    ),
    EventType.SOLAR_OUTPUT_DROP: RouteConfig(
        default_severity=Severity.MEDIUM,
        criticality="medium",
        affected_modules=("energy", "forecast", "mission", "optimizer", "reserve"),
        workflow_name="generation_drop",
    ),
    EventType.BATTERY_LOW: RouteConfig(
        default_severity=Severity.HIGH,
        criticality="high",
        affected_modules=("energy", "reserve", "mission", "optimizer"),
        workflow_name="low_reserve",
    ),
    EventType.HYDROGEN_LOW: RouteConfig(
        default_severity=Severity.HIGH,
        criticality="high",
        affected_modules=("energy", "reserve", "mission", "optimizer"),
        workflow_name="low_reserve",
    ),
    EventType.MISSION_STARTED: RouteConfig(
        default_severity=Severity.LOW,
        criticality="low",
        affected_modules=("mission", "energy", "optimizer", "reserve"),
        workflow_name="mission_start",
    ),
    EventType.MISSION_DEADLINE_APPROACHING: RouteConfig(
        default_severity=Severity.MEDIUM,
        criticality="medium",
        affected_modules=("mission", "energy", "optimizer", "reserve"),
        workflow_name="mission_start",
    ),
    EventType.EQUIPMENT_DEGRADED: RouteConfig(
        default_severity=Severity.HIGH,
        criticality="high",
        affected_modules=("diagnostic", "energy", "forecast", "reserve", "optimizer"),
        workflow_name="equipment_failure",
    ),
    EventType.TURBINE_ANOMALY: RouteConfig(
        default_severity=Severity.HIGH,
        criticality="high",
        affected_modules=("diagnostic", "energy", "forecast", "reserve", "optimizer"),
        workflow_name="equipment_failure",
    ),
    EventType.WEATHER_WARNING: RouteConfig(
        default_severity=Severity.MEDIUM,
        criticality="medium",
        affected_modules=("forecast", "energy", "mission", "reserve", "optimizer"),
        workflow_name="weather_risk",
    ),
    EventType.LOAD_SPIKE: RouteConfig(
        default_severity=Severity.HIGH,
        criticality="high",
        affected_modules=("energy", "mission", "optimizer", "reserve"),
        workflow_name="generation_drop",
    ),
    EventType.COMMUNICATION_LOSS: RouteConfig(
        default_severity=Severity.CRITICAL,
        criticality="critical",
        affected_modules=("diagnostic", "mission", "reserve"),
        workflow_name="equipment_failure",
    ),
}


class EventRouter:
    """
    Classifies events and determines routing.

    Uses the static ROUTING_TABLE for O(1) lookup — no if/else chains.
    """

    def classify(self, event: StationEvent) -> RouteConfig:
        """
        Classify an event and return its routing configuration.

        Raises KeyError if event type is unknown (should not happen
        with the EventType enum, but defensive programming).
        """
        route = ROUTING_TABLE.get(event.event_type)
        if route is None:
            raise ValueError(
                f"Unknown event type: {event.event_type}. "
                f"No route configured in ROUTING_TABLE."
            )
        return route

    def get_affected_modules(self, event: StationEvent) -> tuple[str, ...]:
        """Return the list of modules that need to be consulted."""
        return self.classify(event).affected_modules

    def get_workflow_name(self, event: StationEvent) -> str:
        """Return the workflow name for this event type."""
        return self.classify(event).workflow_name

    def get_severity(self, event: StationEvent) -> Severity:
        """
        Return effective severity.

        Uses the event's own severity if provided, otherwise
        falls back to the routing table default.
        """
        route = self.classify(event)
        # If the event has an explicit severity, respect it
        if event.severity != Severity.MEDIUM:
            return event.severity
        return route.default_severity

    def get_all_routes(self) -> dict[str, dict]:
        """Return the complete routing table (for API/debug)."""
        return {
            et.value: {
                "default_severity": rc.default_severity.value,
                "criticality": rc.criticality,
                "affected_modules": list(rc.affected_modules),
                "workflow_name": rc.workflow_name,
            }
            for et, rc in ROUTING_TABLE.items()
        }
