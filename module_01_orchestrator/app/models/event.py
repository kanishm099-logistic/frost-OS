"""
Frost OS Module 01 — Event Domain Models.

Defines the strongly-typed event model, event type enumeration,
severity levels, and SQLAlchemy persistence model.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, DateTime, Enum, Index, JSON, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


# ── SQLAlchemy Base ───────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared declarative base for all Frost ORM models."""
    pass


# ── Enumerations ──────────────────────────────────────────────────────

class EventType(str, enum.Enum):
    """All station event types the orchestrator can process."""
    WIND_POWER_DROP = "WIND_POWER_DROP"
    SOLAR_OUTPUT_DROP = "SOLAR_OUTPUT_DROP"
    BATTERY_LOW = "BATTERY_LOW"
    HYDROGEN_LOW = "HYDROGEN_LOW"
    MISSION_STARTED = "MISSION_STARTED"
    MISSION_DEADLINE_APPROACHING = "MISSION_DEADLINE_APPROACHING"
    EQUIPMENT_DEGRADED = "EQUIPMENT_DEGRADED"
    TURBINE_ANOMALY = "TURBINE_ANOMALY"
    WEATHER_WARNING = "WEATHER_WARNING"
    LOAD_SPIKE = "LOAD_SPIKE"
    COMMUNICATION_LOSS = "COMMUNICATION_LOSS"


class Severity(str, enum.Enum):
    """Event severity levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_PRIORITY: dict[Severity, int] = {
    Severity.CRITICAL: 0,
    Severity.HIGH: 1,
    Severity.MEDIUM: 2,
    Severity.LOW: 3,
}


# ── Pydantic Domain Model ────────────────────────────────────────────

class StationEvent(BaseModel):
    """
    Strongly-typed station event.

    Every event entering the orchestrator must conform to this schema.
    Validation ensures structural integrity before any processing.
    """

    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique event identifier",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Event timestamp (UTC)",
    )
    source: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Originating system/sensor identifier",
    )
    event_type: EventType = Field(
        ...,
        description="Classified event type",
    )
    severity: Severity = Field(
        default=Severity.MEDIUM,
        description="Event severity level",
    )
    station_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Station identifier",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data payload",
    )
    correlation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Correlation ID for distributed tracing",
    )

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: datetime) -> datetime:
        """Ensure timestamp is timezone-aware and not unreasonably in the future."""
        if v.tzinfo is None:
            raise ValueError("Timestamp must be timezone-aware (UTC preferred)")
        future_limit = datetime.now(timezone.utc).replace(
            second=datetime.now(timezone.utc).second + 60
        )
        # Allow up to 60 seconds clock skew
        if v > future_limit:
            raise ValueError("Timestamp cannot be more than 60 seconds in the future")
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Ensure source identifier is non-empty and stripped."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Source must be a non-empty identifier")
        return stripped

    @property
    def priority_score(self) -> int:
        """Lower integer = higher priority (CRITICAL=0, HIGH=1, MEDIUM=2, LOW=3)."""
        return SEVERITY_PRIORITY.get(self.severity, 2)

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, StationEvent):
            return NotImplemented
        if self.priority_score != other.priority_score:
            return self.priority_score < other.priority_score
        return self.timestamp < other.timestamp


# ── SQLAlchemy ORM Model ──────────────────────────────────────────────

class EventRecord(Base):
    """Persistent storage for station events."""

    __tablename__ = "events"

    event_id = Column(String(36), primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    source = Column(String(255), nullable=False)
    event_type = Column(Enum(EventType, name="event_type_enum"), nullable=False, index=True)
    severity = Column(Enum(Severity, name="severity_enum"), nullable=False)
    station_id = Column(String(100), nullable=False, index=True)
    payload = Column(JSON_TYPE, nullable=False, default={})
    correlation_id = Column(String(36), nullable=False, index=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_events_station_type", "station_id", "event_type"),
    )

    def to_domain(self) -> StationEvent:
        """Convert ORM record to domain model."""
        return StationEvent(
            event_id=str(self.event_id),
            timestamp=self.timestamp,
            source=self.source,
            event_type=self.event_type,
            severity=self.severity,
            station_id=self.station_id,
            payload=self.payload or {},
            correlation_id=self.correlation_id,
        )

    @classmethod
    def from_domain(cls, event: StationEvent) -> "EventRecord":
        """Create ORM record from domain model."""
        return cls(
            event_id=event.event_id,
            timestamp=event.timestamp,
            source=event.source,
            event_type=event.event_type,
            severity=event.severity,
            station_id=event.station_id,
            payload=event.payload,
            correlation_id=event.correlation_id,
        )
