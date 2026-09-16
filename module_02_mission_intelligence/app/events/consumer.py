"""
Frost OS Module 02 — Event Consumer.

Listens to Redis Streams for external station events (e.g. from Module 01 or 08)
and handles idempotent message consumption.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Coroutine

import structlog

logger = structlog.get_logger(__name__)


class MissionEventConsumer:
    """Consumes events from Redis Streams with consumer group support."""

    def __init__(
        self,
        redis_client: Any,
        stream_name: str = "frost:events:mission",
        group_name: str = "mission-intelligence-group",
        consumer_name: str = "consumer-01",
    ) -> None:
        self.redis = redis_client
        self.stream_name = stream_name
        self.group_name = group_name
        self.consumer_name = consumer_name
        self._running = False
        self._handlers: dict[str, list[Callable[[dict[str, Any]], Coroutine[Any, Any, None]]]] = {}

    def register_handler(
        self,
        event_type: str,
        handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """Register an async handler callback for a specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    async def init_group(self) -> None:
        """Ensure consumer group exists."""
        if self.redis is None:
            return
        try:
            await self.redis.xgroup_create(
                self.stream_name,
                self.group_name,
                id="0",
                mkstream=True,
            )
            await logger.ainfo("Created Redis consumer group", group=self.group_name)
        except Exception as e:
            if "BUSYGROUP" in str(e):
                pass  # Group already exists
            else:
                await logger.awarn("Failed to create consumer group", error=str(e))

    async def start(self, poll_interval_seconds: float = 0.5) -> None:
        """Start consumption loop."""
        self._running = True
        await self.init_group()

        while self._running:
            try:
                if self.redis is None:
                    await asyncio.sleep(poll_interval_seconds)
                    continue

                response = await self.redis.xreadgroup(
                    self.group_name,
                    self.consumer_name,
                    {self.stream_name: ">"},
                    count=10,
                    block=1000,
                )

                if response:
                    for stream, messages in response:
                        for msg_id, raw_data in messages:
                            await self._process_message(msg_id, raw_data)

            except asyncio.CancelledError:
                break
            except Exception as e:
                await logger.aerror("Error in consumer loop", error=str(e))
                await asyncio.sleep(poll_interval_seconds)

    async def _process_message(self, msg_id: Any, raw_data: dict[Any, Any]) -> None:
        """Process an individual stream message."""
        try:
            # Decode byte keys if necessary
            data = {}
            for k, v in raw_data.items():
                key_str = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                val_str = v.decode("utf-8") if isinstance(v, bytes) else str(v)
                data[key_str] = val_str

            event_type = data.get("event_type", "")
            payload_str = data.get("payload", "{}")
            payload = json.loads(payload_str)
            data["payload"] = payload

            handlers = self._handlers.get(event_type, [])
            for handler in handlers:
                await handler(data)

            # Acknowledge message
            if self.redis is not None:
                await self.redis.xack(self.stream_name, self.group_name, msg_id)

        except Exception as e:
            await logger.aerror("Failed to process message", msg_id=str(msg_id), error=str(e))

    def stop(self) -> None:
        """Stop consumer loop."""
        self._running = False
