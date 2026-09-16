"""
Frost OS Module 01 — Redis Streams Publisher.

Publishes structured messages to Redis Streams with correlation-ID
injection and error handling.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis
import structlog

from app.events.event_types import Streams

logger = structlog.get_logger(__name__)


class EventPublisher:
    """Async Redis Streams publisher for inter-module communication."""

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    async def publish_event(self, event_data: dict[str, Any]) -> str | None:
        """Publish a station event to the events stream."""
        return await self._publish(Streams.EVENTS, event_data)

    async def publish_decision(self, decision_data: dict[str, Any]) -> str | None:
        """Publish a decision update to the decisions stream."""
        return await self._publish(Streams.DECISIONS, decision_data)

    async def publish_action_plan(self, plan_data: dict[str, Any]) -> str | None:
        """Publish an action plan to the action plans stream."""
        return await self._publish(Streams.ACTION_PLANS, plan_data)

    async def publish_execution_result(self, result_data: dict[str, Any]) -> str | None:
        """Publish an execution result."""
        return await self._publish(Streams.EXECUTION_RESULTS, result_data)

    async def _publish(self, stream: str, data: dict[str, Any]) -> str | None:
        """
        Publish a message to a Redis Stream.

        All payloads are JSON-serialized under a 'data' key.
        Returns the stream message ID on success, None on failure.
        """
        try:
            # Ensure correlation_id is present
            if "correlation_id" not in data:
                import uuid
                data["correlation_id"] = str(uuid.uuid4())

            message = {
                "data": json.dumps(data, default=str),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            message_id = await self._redis.xadd(stream, message)

            await logger.ainfo(
                "Published message to stream",
                stream=stream,
                message_id=message_id,
                correlation_id=data.get("correlation_id"),
            )
            return message_id

        except Exception as exc:
            await logger.aerror(
                "Failed to publish message",
                stream=stream,
                error=str(exc),
                correlation_id=data.get("correlation_id"),
            )
            return None

    async def close(self) -> None:
        """Close the Redis connection."""
        await self._redis.aclose()
