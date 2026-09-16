"""
Redis Streams Event Publisher and Listener.

Publishes optimization lifecycle events and listens for subsystem trigger updates.
Uses event_id, correlation_id, station_id, timestamp schemas.
"""

from __future__ import annotations

import json
import uuid
import structlog
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import redis.asyncio as redis
from app.models.optimization_result import OptimizationResult

logger = structlog.get_logger(__name__)

STREAM_CHANNEL = "frost:events:optimization"


class EventPublisher:
    """Redis Streams Publisher for Module 06 events."""

    def __init__(self, redis_client: Optional[redis.Redis]):
        self.redis = redis_client

    async def publish_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        station_id: str = "POLAR-STATION-ALPHA"
    ) -> Optional[str]:
        """Publish structured event payload to Redis Streams."""
        if not self.redis:
            logger.debug("Redis client disabled — skipping stream event publish", event_type=event_type)
            return None

        event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
        cid = correlation_id or f"CORR-{uuid.uuid4().hex[:8].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()

        event_body = {
            "event_id": event_id,
            "event_type": event_type,
            "correlation_id": cid,
            "station_id": station_id,
            "timestamp": now_iso,
            "payload": json.dumps(payload),
        }

        try:
            msg_id = await self.redis.xadd(STREAM_CHANNEL, event_body)
            logger.info("Published Redis Stream event", event_type=event_type, msg_id=msg_id)
            return msg_id
        except Exception as exc:
            logger.warning("Failed to publish Redis Stream event", error=str(exc))
            return None

    async def publish_optimization_completed(
        self,
        result: OptimizationResult,
        correlation_id: Optional[str] = None
    ) -> Optional[str]:
        """Publish OPTIMIZATION_COMPLETED and PLAN_FEASIBLE/PLAN_INFEASIBLE events."""
        event_type = "PLAN_FEASIBLE" if result.feasible else "PLAN_INFEASIBLE"
        
        payload = {
            "optimization_id": result.optimization_id,
            "station_id": result.station_id,
            "status": result.solver_status,
            "feasible": result.feasible,
            "objective_value": result.objective_value,
            "action_plan_id": result.action_plan.plan_id if result.action_plan else None,
        }

        await self.publish_event("OPTIMIZATION_COMPLETED", payload, correlation_id, result.station_id)
        return await self.publish_event(event_type, payload, correlation_id, result.station_id)
