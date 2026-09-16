"""
Frost OS Module 03 — Energy Event Types and Schemas.

Defines the event stream models emitted across Redis Streams for
Module 01 Orchestrator, Module 06 Optimization, and Module 07 Safety.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class EnergyEventType(str, enum.Enum):
    """Event types published by Energy Intelligence."""
    ENERGY_STATE_UPDATED = "ENERGY_STATE_UPDATED"
    DEFICIT_DETECTED = "DEFICIT_DETECTED"
    SURPLUS_DETECTED = "SURPLUS_DETECTED"
    STORAGE_CRITICAL = "STORAGE_CRITICAL"
    BATTERY_LOW = "BATTERY_LOW"
    GENERATION_DROP = "GENERATION_DROP"
    LOAD_SPIKE = "LOAD_SPIKE"
    TELEMETRY_ANOMALY = "TELEMETRY_ANOMALY"
    ENERGY_ALERT_TRIGGERED = "ENERGY_ALERT_TRIGGERED"


class EnergyEvent(BaseModel):
    """Strongly-typed energy event for Redis Streams messaging."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EnergyEventType
    station_id: str
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
