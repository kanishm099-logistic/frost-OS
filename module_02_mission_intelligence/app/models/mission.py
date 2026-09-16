"""
Frost OS Module 02 — Mission Domain Models.

Defines the core Mission entity, mission classifications, operational states,
state machine transition rules, and SQLAlchemy persistence models.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

from app.models.priority import PriorityLevel

# Universal JSON type (JSONB on PostgreSQL, JSON/TEXT on SQLite)
JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


# ── SQLAlchemy Base ───────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared declarative base for all Module 02 ORM models."""
    pass


# ── Enumerations ──────────────────────────────────────────────────────

class MissionType(str, enum.Enum):
    """Classifications of station workloads."""
    LIFE_SUPPORT = "LIFE_SUPPORT"
    MEDICAL = "MEDICAL"
    RESEARCH = "RESEARCH"
    WEATHER_MONITORING = "WEATHER_MONITORING"
    COMMUNICATION = "COMMUNICATION"
    MAINTENANCE = "MAINTENANCE"
    LABORATORY = "LABORATORY"
    COMPUTING = "COMPUTING"
    HEATING = "HEATING"
    OPERATIONS = "OPERATIONS"
    OFFICE = "OFFICE"
    RECREATION = "RECREATION"
    CUSTOM = "CUSTOM"


class Flexibility(str, enum.Enum):
    """Flexibility degree of a workload."""
    INFLEXIBLE = "INFLEXIBLE"                    # Must run without alteration (e.g. Life Support)
    PARTIALLY_FLEXIBLE = "PARTIALLY_FLEXIBLE"    # Can ramp between min_power and max_power
    FLEXIBLE = "FLEXIBLE"                        # Can shift start time or interrupt briefly
    DEFERRABLE = "DEFERRABLE"                    # Can be suspended or delayed for long periods


class MissionState(str, enum.Enum):
    """Lifecycle states of a mission."""
    CREATED = "CREATED"
    CLASSIFYING = "CLASSIFYING"
    SCHEDULED = "SCHEDULED"
    READY = "READY"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    DEFERRED = "DEFERRED"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"


# Valid state transitions enforced by the state machine
VALID_MISSION_TRANSITIONS: dict[MissionState, list[MissionState]] = {
    MissionState.CREATED: [MissionState.CLASSIFYING, MissionState.SCHEDULED, MissionState.CANCELLED],
    MissionState.CLASSIFYING: [MissionState.SCHEDULED, MissionState.BLOCKED, MissionState.CANCELLED],
    MissionState.SCHEDULED: [MissionState.READY, MissionState.BLOCKED, MissionState.DEFERRED, MissionState.CANCELLED],
    MissionState.BLOCKED: [MissionState.READY, MissionState.SCHEDULED, MissionState.CANCELLED],
    MissionState.DEFERRED: [MissionState.READY, MissionState.SCHEDULED, MissionState.CANCELLED],
    MissionState.READY: [MissionState.RUNNING, MissionState.PAUSED, MissionState.BLOCKED, MissionState.CANCELLED],
    MissionState.RUNNING: [MissionState.PAUSED, MissionState.COMPLETED, MissionState.FAILED, MissionState.CANCELLED],
    MissionState.PAUSED: [MissionState.RUNNING, MissionState.DEFERRED, MissionState.CANCELLED, MissionState.EXPIRED],
    MissionState.COMPLETED: [],  # Terminal
    MissionState.CANCELLED: [],  # Terminal
    MissionState.FAILED: [MissionState.SCHEDULED, MissionState.CANCELLED],  # Can retry
    MissionState.EXPIRED: [MissionState.CANCELLED],
}


def validate_mission_transition(current: MissionState, target: MissionState) -> bool:
    """Validate whether transitioning from current to target state is permissible."""
    allowed = VALID_MISSION_TRANSITIONS.get(current, [])
    return target in allowed


# ── Domain Model ──────────────────────────────────────────────────────

class Mission(BaseModel):
    """
    Strongly-typed mission domain model.

    Represents a discrete station activity or workload profile.
    """
    mission_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for the mission",
    )
    station_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Originating station identifier",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable title of the mission",
    )
    description: str = Field(
        default="",
        description="Operational context or scientific description",
    )
    type: MissionType = Field(
        default=MissionType.RESEARCH,
        description="Categorized mission type",
    )
    priority: PriorityLevel = Field(
        default=PriorityLevel.P2,
        description="Operational priority level (P0 to P4)",
    )
    required_power_kw: float = Field(
        ...,
        gt=0.0,
        description="Nominal operating power in kW",
    )
    min_power_kw: float = Field(
        ...,
        gt=0.0,
        description="Absolute minimum safe operating power in kW",
    )
    max_power_kw: float = Field(
        ...,
        gt=0.0,
        description="Peak power limit in kW",
    )
    expected_duration_minutes: int = Field(
        ...,
        gt=0,
        description="Estimated execution time in minutes",
    )
    deadline: datetime | None = Field(
        default=None,
        description="Absolute completion deadline (UTC)",
    )
    flexibility: Flexibility = Field(
        default=Flexibility.PARTIALLY_FLEXIBLE,
        description="Operational flexibility characteristic",
    )
    energy_required_kwh: float = Field(
        default=0.0,
        ge=0.0,
        description="Total calculated energy required in kWh",
    )
    buffer_kwh: float = Field(
        default=0.0,
        ge=0.0,
        description="Protected energy buffer in kWh",
    )
    protected_energy_kwh: float = Field(
        default=0.0,
        ge=0.0,
        description="Combined base + buffer energy in kWh",
    )
    status: MissionState = Field(
        default=MissionState.CREATED,
        description="Current mission lifecycle state",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="List of prerequisite mission IDs",
    )
    earliest_start: datetime | None = Field(
        default=None,
        description="Earliest permitted start time (UTC)",
    )
    latest_start: datetime | None = Field(
        default=None,
        description="Latest start time to meet deadline (UTC)",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Creation timestamp (UTC)",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last update timestamp (UTC)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible metadata payload",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Strip whitespace and enforce non-empty name."""
        stripped = v.strip()
        if not stripped:
            raise ValueError("Mission name cannot be empty or whitespace only")
        return stripped

    @field_validator("deadline", "earliest_start", "latest_start", "created_at", "updated_at", mode="before")
    @classmethod
    def validate_utc_timezone(cls, v: Any) -> Any:
        """Enforce timezone awareness on all timestamp fields, defaulting naive to UTC."""
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @model_validator(mode="after")
    def validate_power_envelope(self) -> "Mission":
        """Enforce min_power_kw <= required_power_kw <= max_power_kw."""
        if self.min_power_kw > self.required_power_kw:
            raise ValueError(
                f"min_power_kw ({self.min_power_kw}) cannot exceed required_power_kw ({self.required_power_kw})"
            )
        if self.required_power_kw > self.max_power_kw:
            raise ValueError(
                f"required_power_kw ({self.required_power_kw}) cannot exceed max_power_kw ({self.max_power_kw})"
            )
        return self


# ── SQLAlchemy ORM Models ─────────────────────────────────────────────

class MissionRecord(Base):
    """Database record for station missions."""

    __tablename__ = "missions"

    mission_id = Column(String(36), primary_key=True)
    station_id = Column(String(100), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=False, default="")
    type = Column(Enum(MissionType, name="mission_type_enum"), nullable=False, index=True)
    priority = Column(Enum(PriorityLevel, name="priority_level_enum"), nullable=False, index=True)
    required_power_kw = Column(Float, nullable=False)
    min_power_kw = Column(Float, nullable=False)
    max_power_kw = Column(Float, nullable=False)
    expected_duration_minutes = Column(Integer, nullable=False)
    deadline = Column(DateTime(timezone=True), nullable=True, index=True)
    flexibility = Column(Enum(Flexibility, name="flexibility_enum"), nullable=False)
    energy_required_kwh = Column(Float, nullable=False, default=0.0)
    buffer_kwh = Column(Float, nullable=False, default=0.0)
    protected_energy_kwh = Column(Float, nullable=False, default=0.0)
    status = Column(Enum(MissionState, name="mission_state_enum"), nullable=False, index=True)
    dependencies_json = Column(JSON_TYPE, nullable=False, default=[])
    earliest_start = Column(DateTime(timezone=True), nullable=True)
    latest_start = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    metadata_json = Column(JSON_TYPE, nullable=False, default={})

    __table_args__ = (
        Index("ix_missions_station_status", "station_id", "status"),
        Index("ix_missions_priority_status", "priority", "status"),
    )

    def to_domain(self) -> Mission:
        """Convert ORM record to domain Mission model."""
        return Mission(
            mission_id=self.mission_id,
            station_id=self.station_id,
            name=self.name,
            description=self.description,
            type=self.type,
            priority=self.priority,
            required_power_kw=self.required_power_kw,
            min_power_kw=self.min_power_kw,
            max_power_kw=self.max_power_kw,
            expected_duration_minutes=self.expected_duration_minutes,
            deadline=self.deadline,
            flexibility=self.flexibility,
            energy_required_kwh=self.energy_required_kwh,
            buffer_kwh=self.buffer_kwh,
            protected_energy_kwh=self.protected_energy_kwh,
            status=self.status,
            dependencies=self.dependencies_json or [],
            earliest_start=self.earliest_start,
            latest_start=self.latest_start,
            created_at=self.created_at,
            updated_at=self.updated_at,
            metadata=self.metadata_json or {},
        )

    @classmethod
    def from_domain(cls, m: Mission) -> "MissionRecord":
        """Instantiate ORM record from domain Mission model."""
        return cls(
            mission_id=m.mission_id,
            station_id=m.station_id,
            name=m.name,
            description=m.description,
            type=m.type,
            priority=m.priority,
            required_power_kw=m.required_power_kw,
            min_power_kw=m.min_power_kw,
            max_power_kw=m.max_power_kw,
            expected_duration_minutes=m.expected_duration_minutes,
            deadline=m.deadline,
            flexibility=m.flexibility,
            energy_required_kwh=m.energy_required_kwh,
            buffer_kwh=m.buffer_kwh,
            protected_energy_kwh=m.protected_energy_kwh,
            status=m.status,
            dependencies_json=m.dependencies,
            earliest_start=m.earliest_start,
            latest_start=m.latest_start,
            created_at=m.created_at,
            updated_at=m.updated_at,
            metadata_json=m.metadata,
        )


class MissionStateTransitionRecord(Base):
    """Audit record of every mission state transition."""

    __tablename__ = "mission_state_transitions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mission_id = Column(String(36), ForeignKey("missions.mission_id"), nullable=False, index=True)
    from_state = Column(Enum(MissionState, name="mission_state_enum", create_type=False), nullable=False)
    to_state = Column(Enum(MissionState, name="mission_state_enum", create_type=False), nullable=False)
    reason = Column(Text, nullable=True)
    actor = Column(String(255), nullable=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_transitions_mission_ts", "mission_id", "timestamp"),
    )


class AuditLogRecord(Base):
    """Append-only audit trail for mission operations."""

    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
    station_id = Column(String(100), nullable=False, index=True)
    mission_id = Column(String(36), nullable=True, index=True)
    correlation_id = Column(String(36), nullable=False, index=True)
    actor = Column(String(255), nullable=False)
    action = Column(String(255), nullable=False)
    details = Column(JSON_TYPE, nullable=True)
    status = Column(String(50), nullable=False, default="success")

    __table_args__ = (
        Index("ix_audit_station_ts", "station_id", "timestamp"),
    )
