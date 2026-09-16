"""
Frost OS Module 04 — Redis Streams Event Publisher.

Publishes 10 standard forecast event types:
1. FORECAST_UPDATED
2. LOW_RENEWABLE_FORECAST
3. ENERGY_DEFICIT_FORECAST
4. WIND_DROP_FORECAST
5. SOLAR_DROP_FORECAST
6. HIGH_LOAD_FORECAST
7. BATTERY_DEPLETION_FORECAST
8. HYDROGEN_DEPLETION_FORECAST
9. FORECAST_DEGRADED
10. MODEL_PERFORMANCE_DEGRADED
"""

from __future__ import annotations

import enum
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

try:
    import redis.asyncio as redis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False


class ForecastEventType(str, enum.Enum):
    """Supported 10 forecast stream event types."""
    FORECAST_UPDATED = "FORECAST_UPDATED"
    LOW_RENEWABLE_FORECAST = "LOW_RENEWABLE_FORECAST"
    ENERGY_DEFICIT_FORECAST = "ENERGY_DEFICIT_FORECAST"
    WIND_DROP_FORECAST = "WIND_DROP_FORECAST"
    SOLAR_DROP_FORECAST = "SOLAR_DROP_FORECAST"
    HIGH_LOAD_FORECAST = "HIGH_LOAD_FORECAST"
    BATTERY_DEPLETION_FORECAST = "BATTERY_DEPLETION_FORECAST"
    HYDROGEN_DEPLETION_FORECAST = "HYDROGEN_DEPLETION_FORECAST"
    FORECAST_DEGRADED = "FORECAST_DEGRADED"
    MODEL_PERFORMANCE_DEGRADED = "MODEL_PERFORMANCE_DEGRADED"


class ForecastEventPublisher:
    """Publishes structured events to Redis Streams with in-memory fallback."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        stream_name: str = "frost:events:forecast",
    ) -> None:
        self.redis_url = redis_url
        self.stream_name = stream_name
        self._redis_client: Any = None
        self._published_history: list[dict[str, Any]] = []

    async def connect(self) -> None:
        """Attempt connection to Redis instance."""
        if not HAS_REDIS:
            return
        try:
            self._redis_client = redis.from_url(
                self.redis_url, decode_responses=True, socket_timeout=1.5
            )
            await self._redis_client.ping()
            logger.info("redis_stream_connected", stream=self.stream_name)
        except Exception as e:
            logger.warning("redis_stream_connection_fallback_to_memory", error=str(e))
            self._redis_client = None

    async def close(self) -> None:
        if self._redis_client:
            await self._redis_client.aclose()
            self._redis_client = None

    async def publish_event(
        self,
        event_type: ForecastEventType,
        station_id: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> str:
        """
        Publish structured event containing:
        event_id, correlation_id, station_id, timestamp, event_type, and payload.
        """
        event_id = str(uuid.uuid4())
        corr_id = correlation_id or str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()

        event_envelope = {
            "event_id": event_id,
            "correlation_id": corr_id,
            "station_id": station_id,
            "event_type": event_type.value if hasattr(event_type, "value") else str(event_type),
            "timestamp": now_iso,
            "payload": payload,
        }

        # In-memory history buffer (useful for unit tests and local inspection)
        self._published_history.append(event_envelope)

        if self._redis_client:
            try:
                msg_data = {
                    "event_id": event_id,
                    "correlation_id": corr_id,
                    "station_id": station_id,
                    "event_type": event_type.value if hasattr(event_type, "value") else str(event_type),
                    "timestamp": now_iso,
                    "data": json.dumps(payload),
                }
                stream_id = await self._redis_client.xadd(self.stream_name, msg_data)
                return str(stream_id)
            except Exception as e:
                logger.warning("redis_xadd_failed_falling_back_to_memory", error=str(e))

        return event_id

    def get_published_events(self) -> list[dict[str, Any]]:
        """Return all published events in this session."""
        return list(self._published_history)
