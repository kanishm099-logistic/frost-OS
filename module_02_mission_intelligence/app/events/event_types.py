"""
Frost OS Module 02 — Mission Event Types and Schemas.

Defines the event stream models emitted across Redis Streams.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, Field


class MissionEventType(str, enum.Enum):
    """Event types published by Mission Intelligence."""
    MISSION_CREATED = "MISSION_CREATED"
    MISSION_UPDATED = "MISSION_UPDATED"
    MISSION_STARTED = "MISSION_STARTED"
    MISSION_PAUSED = "MISSION_PAUSED"
    MISSION_COMPLETED = "MISSION_COMPLETED"
    MISSION_DEADLINE_APPROACHING = "MISSION_DEADLINE_APPROACHING"
    MISSION_EXPIRED = "MISSION_EXPIRED"
    MISSION_CANCELLED = "MISSION_CANCELLED"


class MissionEvent(BaseModel):
    """Strongly-typed mission event for Redis Streams messaging."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: MissionEventType
    station_id: str
    mission_id: str
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
