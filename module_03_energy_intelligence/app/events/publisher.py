"""
Frost OS Module 03 — Energy Event Publisher.

Publishes real-time energy telemetry events, state updates, and anomaly alerts
to Redis Streams with correlation tracking and structured payloads.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.events.event_types import EnergyEvent, EnergyEventType
from app.models.energy_state import EnergyState

logger = structlog.get_logger(__name__)


class EnergyEventPublisher:
    """Publishes strongly-typed energy events to Redis Streams."""

    def __init__(
        self,
        redis_client: Any,
        stream_name: str = "frost:events:energy",
    ) -> None:
        self.redis = redis_client
        self.stream_name = stream_name
        self.published_events: list[EnergyEvent] = []

    async def publish(self, event: EnergyEvent) -> str:
        """
        Publish an energy event to the Redis Stream.
        Returns the Redis message ID.
        """
        message_data = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "station_id": event.station_id,
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
                    "Failed to publish event to Redis stream; recorded in memory buffer",
                    stream=self.stream_name,
                    event_id=event.event_id,
                    error=str(e),
                )
                msg_id = f"fallback-{event.event_id}"

        self.published_events.append(event)
        await logger.ainfo(
            "Published energy event",
            event_type=event.event_type.value,
            station_id=event.station_id,
            event_id=event.event_id,
            msg_id=msg_id,
        )
        return msg_id

    async def publish_state_update(
        self,
        state: EnergyState,
        correlation_id: str | None = None,
    ) -> str:
        """Convenience method to publish full EnergyState snapshot event."""
        from uuid import uuid4
        event = EnergyEvent(
            event_type=EnergyEventType.ENERGY_STATE_UPDATED,
            station_id=state.station_id,
            correlation_id=correlation_id or str(uuid4()),
            payload={
                "state_id": state.state_id,
                "timestamp": state.timestamp.isoformat(),
                "total_generation_kw": state.generation.total_generation_kw,
                "total_load_kw": state.load.total_load_kw,
                "net_power_kw": state.net_power_kw,
                "battery_soc_pct": state.battery.soc_pct,
                "battery_runway_hours": state.battery.runway_hours,
                "status": state.status.value,
                "active_alerts": state.active_alerts,
            },
        )
        return await self.publish(event)

    async def publish_alert(
        self,
        alert_type: EnergyEventType | str,
        station_id: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> str:
        """Convenience method to publish an alert event."""
        from uuid import uuid4
        if isinstance(alert_type, str):
            try:
                e_type = EnergyEventType(alert_type)
            except ValueError:
                e_type = EnergyEventType.ENERGY_ALERT_TRIGGERED
        else:
            e_type = alert_type

        event = EnergyEvent(
            event_type=e_type,
            station_id=station_id,
            correlation_id=correlation_id or str(uuid4()),
            payload=payload,
        )
        return await self.publish(event)
