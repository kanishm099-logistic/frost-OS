"""
Frost OS Module 01 — Priority Event Queue.

Provides an asynchronous priority-driven event queue that ensures
CRITICAL and HIGH severity station events are prioritized and processed
ahead of MEDIUM and LOW routine telemetry/events.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List, Optional
import structlog

from app.models.event import Severity, StationEvent

logger = structlog.get_logger(__name__)


@dataclass(order=True)
class PrioritizedEventItem:
    """Queue wrapper tuple ordered by priority_score, then timestamp."""
    priority_score: int
    timestamp: float
    event: StationEvent = field(compare=False)
    future: Optional[asyncio.Future] = field(default=None, compare=False)


class PriorityEventQueue:
    """
    Asynchronous priority-based event processing queue.

    Ensures that CRITICAL (0) and HIGH (1) events bypass lower-priority
    routine events (MEDIUM=2, LOW=3).
    """

    def __init__(self, maxsize: int = 1000) -> None:
        self._queue: asyncio.PriorityQueue[PrioritizedEventItem] = asyncio.PriorityQueue(maxsize=maxsize)
        self._pending_items: List[PrioritizedEventItem] = []
        self._processed_count: int = 0
        self._preemption_count: int = 0
        self._current_processing: Optional[dict[str, Any]] = None
        self._history: List[dict[str, Any]] = []

    async def enqueue(self, event: StationEvent) -> None:
        """Enqueue an event based on its priority."""
        priority_score = event.priority_score
        item = PrioritizedEventItem(
            priority_score=priority_score,
            timestamp=time.time(),
            event=event,
        )
        self._pending_items.append(item)
        # Keep pending sorted by priority for inspection
        self._pending_items.sort(key=lambda x: (x.priority_score, x.timestamp))
        await self._queue.put(item)

        await logger.ainfo(
            "Event enqueued to priority queue",
            event_id=event.event_id,
            event_type=event.event_type.value,
            severity=event.severity.value,
            priority_score=priority_score,
            queue_depth=self._queue.qsize(),
        )

    async def get_next(self) -> PrioritizedEventItem:
        """Fetch the highest-priority pending event."""
        item = await self._queue.get()
        if item in self._pending_items:
            self._pending_items.remove(item)
        self._current_processing = {
            "event_id": item.event.event_id,
            "event_type": item.event.event_type.value,
            "severity": item.event.severity.value,
            "priority_score": item.priority_score,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        return item

    def mark_completed(self, item: PrioritizedEventItem, result: dict[str, Any]) -> None:
        """Mark an event processing as complete."""
        self._processed_count += 1
        record = {
            "event_id": item.event.event_id,
            "event_type": item.event.event_type.value,
            "severity": item.event.severity.value,
            "priority_score": item.priority_score,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": result.get("status", "success"),
            "decision_id": result.get("decision_id"),
        }
        self._history.insert(0, record)
        if len(self._history) > 20:
            self._history.pop()
        self._current_processing = None
        self._queue.task_done()

    def record_processed_event(self, event: StationEvent, result: dict[str, Any]) -> None:
        """Directly record that an event was processed (for tracking metrics)."""
        self._processed_count += 1
        record = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "severity": event.severity.value,
            "priority_score": event.priority_score,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": result.get("status", "success"),
            "decision_id": result.get("decision_id"),
        }
        self._history.insert(0, record)
        if len(self._history) > 20:
            self._history.pop()

    def get_status(self) -> dict[str, Any]:
        """Return snapshot of the priority event queue state."""
        counts_by_severity = {
            Severity.CRITICAL.value: sum(1 for p in self._pending_items if p.event.severity == Severity.CRITICAL),
            Severity.HIGH.value: sum(1 for p in self._pending_items if p.event.severity == Severity.HIGH),
            Severity.MEDIUM.value: sum(1 for p in self._pending_items if p.event.severity == Severity.MEDIUM),
            Severity.LOW.value: sum(1 for p in self._pending_items if p.event.severity == Severity.LOW),
        }

        queued_events = [
            {
                "event_id": item.event.event_id,
                "event_type": item.event.event_type.value,
                "severity": item.event.severity.value,
                "priority_score": item.priority_score,
                "source": item.event.source,
                "enqueued_ago_seconds": round(time.time() - item.timestamp, 2),
            }
            for item in self._pending_items[:10]
        ]

        return {
            "queue_depth": self._queue.qsize(),
            "counts_by_severity": counts_by_severity,
            "currently_processing": self._current_processing,
            "queued_events_preview": queued_events,
            "total_processed": self._processed_count,
            "recent_processed": self._history[:5],
        }
