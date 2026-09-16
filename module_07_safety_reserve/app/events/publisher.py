"""
Redis Streams Safety Event Publisher.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)


class SafetyEventPublisher:
    """Publishes safety validation events to Redis Streams."""

    def __init__(self, redis_url: str, stream_name: str = "frost:events:safety"):
        self.redis_url = redis_url
        self.stream_name = stream_name
        self._client: Optional[redis.Redis] = None

    async def connect(self):
        try:
            self._client = redis.from_url(self.redis_url, decode_responses=False)
            await self._client.ping()
            logger.info("Connected to Redis event stream", stream=self.stream_name)
        except Exception as exc:
            logger.warning("Redis connection unavailable for publisher — running without event publishing", error=str(exc))
            self._client = None

    async def disconnect(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def publish(self, event_type: str, station_id: str, payload: Dict[str, Any]) -> Optional[str]:
        """Publish structured safety event to Redis Stream."""
        if not self._client:
            return None

        event_data = {
            "event_type": event_type,
            "station_id": station_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": json.dumps(payload, default=str),
        }

        try:
            msg_id = await self._client.xadd(self.stream_name, event_data)
            logger.info("Published safety event", event_type=event_type, msg_id=msg_id)
            return msg_id.decode("utf-8") if isinstance(msg_id, bytes) else str(msg_id)
        except Exception as exc:
            logger.warning("Failed to publish safety event", error=str(exc))
            return None
