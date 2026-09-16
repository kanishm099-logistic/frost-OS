"""
Frost OS Module 01 — Redis Streams Consumer.

Consumes events from Redis Streams with consumer-group management,
idempotent processing, ACK handling, and graceful shutdown.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Awaitable

import redis.asyncio as redis
import structlog

from app.events.event_types import ConsumerGroups, Streams, PROCESSED_EVENTS_KEY
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class EventConsumer:
    """
    Async Redis Streams consumer with idempotent processing.

    Uses consumer groups to allow horizontal scaling.
    Tracks processed event IDs in a Redis SET to prevent duplicates.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        settings: Settings,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self._redis = redis_client
        self._settings = settings
        self._handler = handler
        self._running = False
        self._group = settings.redis_consumer_group
        self._consumer = settings.redis_consumer_name
        self._idempotency_ttl = settings.event_idempotency_ttl_seconds

    async def start(self) -> None:
        """Start consuming events from the events stream."""
        await self._ensure_consumer_group(Streams.EVENTS, self._group)
        await self._ensure_consumer_group(Streams.EXECUTION_RESULTS, self._group)
        self._running = True

        await logger.ainfo(
            "Event consumer started",
            group=self._group,
            consumer=self._consumer,
        )

        while self._running:
            try:
                # Read from multiple streams
                messages = await self._redis.xreadgroup(
                    groupname=self._group,
                    consumername=self._consumer,
                    streams={
                        Streams.EVENTS: ">",
                        Streams.EXECUTION_RESULTS: ">",
                    },
                    count=10,
                    block=5000,  # 5 second block timeout
                )

                if messages:
                    for stream_name, stream_messages in messages:
                        for message_id, message_data in stream_messages:
                            await self._process_message(
                                stream_name.decode() if isinstance(stream_name, bytes) else stream_name,
                                message_id.decode() if isinstance(message_id, bytes) else message_id,
                                message_data,
                            )

            except asyncio.CancelledError:
                await logger.ainfo("Event consumer cancellation requested")
                break
            except Exception as exc:
                await logger.aerror("Error in event consumer loop", error=str(exc))
                await asyncio.sleep(1)  # Backoff on error

        await logger.ainfo("Event consumer stopped")

    async def stop(self) -> None:
        """Signal the consumer to stop."""
        self._running = False

    async def _process_message(
        self,
        stream: str,
        message_id: str,
        raw_data: dict[bytes, bytes],
    ) -> None:
        """Process a single message with idempotency check."""
        try:
            # Decode message data
            decoded = {}
            for k, v in raw_data.items():
                key = k.decode() if isinstance(k, bytes) else k
                val = v.decode() if isinstance(v, bytes) else v
                decoded[key] = val

            # Parse the JSON data field
            data = json.loads(decoded.get("data", "{}"))
            event_id = data.get("event_id", message_id)

            # Idempotency check — skip if already processed
            if await self._is_duplicate(event_id):
                await logger.ainfo(
                    "Skipping duplicate event",
                    event_id=event_id,
                    stream=stream,
                )
                await self._redis.xack(stream, self._group, message_id)
                return

            # Process the event
            await self._handler(data)

            # Mark as processed
            await self._mark_processed(event_id)

            # ACK the message
            await self._redis.xack(stream, self._group, message_id)

            await logger.ainfo(
                "Processed message",
                stream=stream,
                message_id=message_id,
                event_id=event_id,
            )

        except Exception as exc:
            await logger.aerror(
                "Failed to process message",
                stream=stream,
                message_id=message_id,
                error=str(exc),
            )
            # Do NOT ACK — message will be re-delivered

    async def _is_duplicate(self, event_id: str) -> bool:
        """Check if an event has already been processed."""
        return await self._redis.sismember(PROCESSED_EVENTS_KEY, event_id)

    async def _mark_processed(self, event_id: str) -> None:
        """Mark an event as processed (with TTL for cleanup)."""
        await self._redis.sadd(PROCESSED_EVENTS_KEY, event_id)
        # Set TTL on the set periodically (Redis doesn't support per-member TTL on sets)
        await self._redis.expire(PROCESSED_EVENTS_KEY, self._idempotency_ttl)

    async def _ensure_consumer_group(self, stream: str, group: str) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            await self._redis.xgroup_create(stream, group, id="0", mkstream=True)
            await logger.ainfo("Created consumer group", stream=stream, group=group)
        except redis.ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                pass  # Group already exists
            else:
                raise
