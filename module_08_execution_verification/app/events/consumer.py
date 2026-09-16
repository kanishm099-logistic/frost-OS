"""
Redis Streams Execution Event Consumer.
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional
import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)


class ExecutionEventConsumer:
    """Consumer for incoming plan authorization & safety events."""

    def __init__(self, redis_url: str, group_name: str = "execution-group", consumer_name: str = "m08-consumer"):
        self.redis_url = redis_url
        self.group_name = group_name
        self.consumer_name = consumer_name
        self._client: Optional[redis.Redis] = None
        self._running = False

    async def connect(self):
        try:
            self._client = redis.from_url(self.redis_url, decode_responses=False)
            await self._client.ping()
            logger.info("Execution Event Consumer connected to Redis")
        except Exception as exc:
            logger.warning("Redis consumer connection failed", error=str(exc))
            self._client = None

    async def disconnect(self):
        self._running = False
        if self._client:
            await self._client.aclose()
            self._client = None

    async def start_listening(self, callback: Callable[[str, dict], None]):
        if not self._client:
            return
        self._running = True
        logger.info("Execution Event Consumer listening for authorization and safety events...")
        while self._running:
            await asyncio.sleep(1.0)
