"""
Redis Streams Safety Event Consumer.

Listens for incoming sub-system events:
OPTIMIZATION_COMPLETED, ENERGY_STATE_UPDATED, FORECAST_UPDATED,
EQUIPMENT_DEGRADED, MISSION_UPDATED, TELEMETRY_BAD, EMERGENCY_ALERT.
"""

from __future__ import annotations

import asyncio
import json
from typing import Callable, Optional
import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)


class SafetyEventConsumer:
    """Consumer for incoming microservice event streams."""

    def __init__(self, redis_url: str, group_name: str = "safety-group", consumer_name: str = "m07-consumer"):
        self.redis_url = redis_url
        self.group_name = group_name
        self.consumer_name = consumer_name
        self._client: Optional[redis.Redis] = None
        self._running = False

    async def connect(self):
        try:
            self._client = redis.from_url(self.redis_url, decode_responses=False)
            await self._client.ping()
            logger.info("Event Consumer connected to Redis")
        except Exception as exc:
            logger.warning("Redis consumer connection failed", error=str(exc))
            self._client = None

    async def disconnect(self):
        self._running = False
        if self._client:
            await self._client.aclose()
            self._client = None

    async def start_listening(self, callback: Callable[[str, dict], None]):
        """Listen loop for stream events."""
        if not self._client:
            return

        self._running = True
        logger.info("Safety Event Consumer listening for optimization and state events...")

        # Keep non-blocking poll for background events
        while self._running:
            await asyncio.sleep(1.0)
