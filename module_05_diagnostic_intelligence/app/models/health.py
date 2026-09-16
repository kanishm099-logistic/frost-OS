"""
Frost OS Module 05 — Health Domain & ORM Models.

Equipment health scoring, state classification, and contributing factor
tracking for diagnostic health assessment.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import (
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    Index,
    String,
)

from app.models.equipment import Base, JSON_TYPE


# ── Enumerations ──────────────────────────────────────────────────────

class HealthState(str, enum.Enum):
    """Equipment health classification states."""
    HEALTHY = "HEALTHY"        # Score ≥ 85 — operating normally
    MONITORED = "MONITORED"    # Score 70-84 — minor concerns, watchlist
    DEGRADED = "DEGRADED"      # Score 50-69 — measurable performance loss
    AT_RISK = "AT_RISK"        # Score 30-49 — significant risk of failure
    CRITICAL = "CRITICAL"      # Score < 30 — imminent failure risk
    UNKNOWN = "UNKNOWN"        # Insufficient data for assessment


class DataQuality(str, enum.Enum):
    """Quality indicator for diagnostic data inputs."""
    GOOD = "GOOD"
    DEGRADED = "DEGRADED"
    ESTIMATED = "ESTIMATED"
    STALE_INPUT = "STALE_INPUT"
    INSUFFICIENT = "INSUFFICIENT"


# ── Pydantic Domain Models ───────────────────────────────────────────

class ContributingFactor(BaseModel):
    """A factor contributing to health score calculation."""
    factor: str = Field(..., description="Factor name (e.g. 'anomaly_penalty')")
    value: float = Field(..., description="Numeric contribution to score")
    description: str = Field(default="", description="Human-readable explanation")
    weight: float = Field(default=1.0, ge=0.0, le=1.0, description="Factor weight")


class ScoringBreakdown(BaseModel):
    """Transparent health score calculation breakdown."""
    base_score: float = Field(default=100.0, description="Starting base score")
    anomaly_penalty: float = Field(default=0.0, ge=0.0, description="Penalty from active anomalies")
    residual_penalty: float = Field(default=0.0, ge=0.0, description="Penalty from residual deviations")
    degradation_penalty: float = Field(default=0.0, ge=0.0, description="Penalty from long-term degradation")
    maintenance_bonus: float = Field(default=0.0, ge=0.0, description="Bonus from recent maintenance")
    final_score: float = Field(default=100.0, ge=0.0, le=100.0)
    formula: str = Field(
        default="score = max(0, 100 - anomaly_penalty - residual_penalty - degradation_penalty + maintenance_bonus)",
        description="Scoring formula used",
    )


class EquipmentHealth(BaseModel):
    """Complete health assessment for a single equipment asset."""
    health_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    equipment_id: str = Field(..., description="Assessed equipment")
    station_id: str = Field(..., description="Station identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    health_score: float = Field(
        default=100.0, ge=0.0, le=100.0,
        description="Overall health score 0-100",
    )
    health_state: HealthState = Field(
        default=HealthState.HEALTHY,
        description="Classified health state",
    )
    contributing_factors: list[ContributingFactor] = Field(
        default_factory=list,
        description="Factors contributing to health score",
    )
    scoring_breakdown: ScoringBreakdown = Field(
        default_factory=ScoringBreakdown,
        description="Transparent scoring calculation",
    )
    data_quality: DataQuality = Field(
        default=DataQuality.GOOD,
        description="Quality of input data used for assessment",
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Confidence in the health assessment",
    )
    anomaly_count: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ── SQLAlchemy ORM Model ─────────────────────────────────────────────

class HealthStateRecord(Base):
    """Persistent equipment health state record (TimescaleDB hypertable candidate)."""

    __tablename__ = "health_states"

    health_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    equipment_id = Column(String(100), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    health_score = Column(Float, nullable=False, default=100.0)
    health_state = Column(
        SQLEnum(HealthState, name="health_state_enum"),
        nullable=False, index=True,
    )
    scoring_breakdown_json = Column(JSON_TYPE, nullable=False, default={})
    contributing_factors_json = Column(JSON_TYPE, nullable=False, default=[])
    data_quality = Column(
        SQLEnum(DataQuality, name="data_quality_enum"),
        nullable=False, default="GOOD",
    )
    confidence = Column(Float, nullable=False, default=1.0)
    anomaly_count = Column(Float, nullable=False, default=0)
    metadata_json = Column(JSON_TYPE, nullable=False, default={})

    __table_args__ = (
        Index("ix_health_equipment_ts", "equipment_id", "timestamp"),
        Index("ix_health_station_state", "station_id", "health_state"),
    )

    def to_domain(self) -> EquipmentHealth:
        """Convert ORM record to domain EquipmentHealth."""
        return EquipmentHealth(
            health_id=self.health_id,
            equipment_id=self.equipment_id,
            station_id=self.station_id,
            timestamp=self.timestamp,
            health_score=self.health_score,
            health_state=self.health_state,
            scoring_breakdown=ScoringBreakdown(**(self.scoring_breakdown_json or {})),
            contributing_factors=[
                ContributingFactor(**f) for f in (self.contributing_factors_json or [])
            ],
            data_quality=self.data_quality,
            confidence=self.confidence,
            anomaly_count=int(self.anomaly_count),
            metadata=self.metadata_json or {},
        )

    @classmethod
    def from_domain(cls, h: EquipmentHealth) -> "HealthStateRecord":
        """Create ORM record from domain EquipmentHealth."""
        return cls(
            health_id=h.health_id,
            equipment_id=h.equipment_id,
            station_id=h.station_id,
            timestamp=h.timestamp,
            health_score=h.health_score,
            health_state=h.health_state,
            scoring_breakdown_json=h.scoring_breakdown.model_dump(),
            contributing_factors_json=[f.model_dump() for f in h.contributing_factors],
            data_quality=h.data_quality,
            confidence=h.confidence,
            anomaly_count=h.anomaly_count,
            metadata_json=h.metadata,
        )
