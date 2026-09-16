"""
Frost OS Module 05 — Diagnostic Event Publisher.

Publishes diagnostic events to Redis Streams with correlation tracking
and structured payloads. Falls back to in-memory buffer when Redis
is unavailable.
"""

from __future__ import annotations

import enum
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class DiagnosticEventType(str, enum.Enum):
    """Event types published by Diagnostic Intelligence."""
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    EQUIPMENT_DEGRADED = "EQUIPMENT_DEGRADED"
    EQUIPMENT_HEALTH_CHANGED = "EQUIPMENT_HEALTH_CHANGED"
    TURBINE_ICING_RISK = "TURBINE_ICING_RISK"
    BATTERY_ANOMALY = "BATTERY_ANOMALY"
    BATTERY_THERMAL_RISK = "BATTERY_THERMAL_RISK"
    SOLAR_OUTPUT_ANOMALY = "SOLAR_OUTPUT_ANOMALY"
    HYDROGEN_SYSTEM_ANOMALY = "HYDROGEN_SYSTEM_ANOMALY"
    INVERTER_ANOMALY = "INVERTER_ANOMALY"
    SENSOR_FAULT = "SENSOR_FAULT"
    EQUIPMENT_FAILURE_RISK = "EQUIPMENT_FAILURE_RISK"
    DIAGNOSTIC_DEGRADED = "DIAGNOSTIC_DEGRADED"


class DiagnosticEvent(BaseModel):
    """Strongly-typed diagnostic event for Redis Streams."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: DiagnosticEventType
    station_id: str
    equipment_id: str = ""
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)


class DiagnosticEventPublisher:
    """Publishes diagnostic events to Redis Streams."""

    def __init__(
        self,
        redis_client: Any = None,
        stream_name: str = "frost:events:diagnostic",
    ) -> None:
        self.redis = redis_client
        self.stream_name = stream_name
        self.published_events: list[DiagnosticEvent] = []

    async def publish(self, event: DiagnosticEvent) -> str:
        """Publish a diagnostic event to Redis Stream."""
        message_data = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "station_id": event.station_id,
            "equipment_id": event.equipment_id,
            "correlation_id": event.correlation_id,
            "timestamp": event.timestamp.isoformat(),
            "payload": json.dumps(event.payload),
        }

        msg_id = f"mock-{event.event_id}"
        if self.redis is not None:
            try:
                msg_id = await self.redis.xadd(self.stream_name, message_data)
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode("utf-8")
            except Exception as e:
                await logger.awarning(
                    "redis_publish_failed",
                    stream=self.stream_name,
                    event_id=event.event_id,
                    error=str(e),
                )
                msg_id = f"fallback-{event.event_id}"

        self.published_events.append(event)
        await logger.ainfo(
            "diagnostic_event_published",
            event_type=event.event_type.value,
            equipment_id=event.equipment_id,
            station_id=event.station_id,
            msg_id=msg_id,
        )
        return msg_id

    async def publish_anomaly(
        self,
        station_id: str,
        equipment_id: str,
        anomaly_data: dict[str, Any],
        equipment_type: str = "",
        correlation_id: str | None = None,
    ) -> str:
        """Publish an anomaly detection event."""
        # Route to equipment-specific event type
        event_type = self._route_event_type(equipment_type, anomaly_data)

        event = DiagnosticEvent(
            event_type=event_type,
            station_id=station_id,
            equipment_id=equipment_id,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload=anomaly_data,
        )
        return await self.publish(event)

    async def publish_health_change(
        self,
        station_id: str,
        equipment_id: str,
        health_data: dict[str, Any],
        correlation_id: str | None = None,
    ) -> str:
        """Publish equipment health change event."""
        event = DiagnosticEvent(
            event_type=DiagnosticEventType.EQUIPMENT_HEALTH_CHANGED,
            station_id=station_id,
            equipment_id=equipment_id,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload=health_data,
        )
        return await self.publish(event)

    async def publish_failure_risk(
        self,
        station_id: str,
        equipment_id: str,
        risk_data: dict[str, Any],
        correlation_id: str | None = None,
    ) -> str:
        """Publish equipment failure risk event."""
        event = DiagnosticEvent(
            event_type=DiagnosticEventType.EQUIPMENT_FAILURE_RISK,
            station_id=station_id,
            equipment_id=equipment_id,
            correlation_id=correlation_id or str(uuid.uuid4()),
            payload=risk_data,
        )
        return await self.publish(event)

    def _route_event_type(
        self,
        equipment_type: str,
        anomaly_data: dict[str, Any],
    ) -> DiagnosticEventType:
        """Route to equipment-specific event type."""
        eq_type = equipment_type.upper()

        # Check for specific patterns first
        if "icing" in str(anomaly_data).lower():
            return DiagnosticEventType.TURBINE_ICING_RISK
        if "thermal" in str(anomaly_data).lower() and "battery" in eq_type.lower():
            return DiagnosticEventType.BATTERY_THERMAL_RISK
        if "sensor" in str(anomaly_data).lower():
            return DiagnosticEventType.SENSOR_FAULT

        routing = {
            "WIND_TURBINE": DiagnosticEventType.ANOMALY_DETECTED,
            "SOLAR_ARRAY": DiagnosticEventType.SOLAR_OUTPUT_ANOMALY,
            "BATTERY": DiagnosticEventType.BATTERY_ANOMALY,
            "HYDROGEN_TANK": DiagnosticEventType.HYDROGEN_SYSTEM_ANOMALY,
            "ELECTROLYZER": DiagnosticEventType.HYDROGEN_SYSTEM_ANOMALY,
            "FUEL_CELL": DiagnosticEventType.HYDROGEN_SYSTEM_ANOMALY,
            "INVERTER": DiagnosticEventType.INVERTER_ANOMALY,
            "CONVERTER": DiagnosticEventType.INVERTER_ANOMALY,
            "SENSOR": DiagnosticEventType.SENSOR_FAULT,
        }
        return routing.get(eq_type, DiagnosticEventType.ANOMALY_DETECTED)

    def get_published_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recently published events (for WebSocket/debug)."""
        recent = self.published_events[-limit:]
        return [e.model_dump(mode="json") for e in recent]
