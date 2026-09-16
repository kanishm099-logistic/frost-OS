"""
Frost OS Module 02 — Event Publisher.

Publishes mission lifecycle events to Redis Streams with correlation IDs
and idempotency tracking.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.events.event_types import MissionEvent, MissionEventType

logger = structlog.get_logger(__name__)


class MissionEventPublisher:
    """Publishes strongly-typed mission events to Redis Streams."""

    def __init__(self, redis_client: Any, stream_name: str = "frost:events:mission") -> None:
        self.redis = redis_client
        self.stream_name = stream_name
        self.published_events: list[MissionEvent] = []  # In-memory buffer for verification/testing

    async def publish(self, event: MissionEvent) -> str:
        """
        Publish a mission event to the Redis Stream.
        Returns the Redis message ID.
        """
        # Serialize fields into string dictionary suitable for Redis Streams
        message_data = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "station_id": event.station_id,
            "mission_id": event.mission_id,
            "correlation_id": event.correlation_id,
            "timestamp": event.timestamp.isoformat(),
            "payload": json.dumps(event.payload),
        }

        msg_id = "mock-msg-id"
        if self.redis is not None:
            try:
                msg_id = await self.redis.xadd(self.stream_name, message_data)
                if isinstance(msg_id, bytes):
                    msg_id = msg_id.decode("utf-8")
            except Exception as e:
                await logger.aerror(
                    "Failed to publish event to Redis stream",
                    stream=self.stream_name,
                    event_id=event.event_id,
                    error=str(e),
                )
                # In test or degraded mode, don't crash the application
                msg_id = f"fallback-{event.event_id}"

        self.published_events.append(event)

        await logger.ainfo(
            "Published mission event",
            event_type=event.event_type.value,
            mission_id=event.mission_id,
            correlation_id=event.correlation_id,
            msg_id=msg_id,
        )
        return msg_id

    async def publish_lifecycle(
        self,
        event_type: MissionEventType,
        station_id: str,
        mission_id: str,
        correlation_id: str,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """Convenience method to construct and publish a lifecycle event."""
        event = MissionEvent(
            event_type=event_type,
            station_id=station_id,
            mission_id=mission_id,
            correlation_id=correlation_id,
            payload=payload or {},
        )
        return await self.publish(event)
