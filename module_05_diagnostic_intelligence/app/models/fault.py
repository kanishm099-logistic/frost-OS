"""
Frost OS Module 05 — Fault Hypothesis Domain & ORM Models.

Defines fault classification results with evidence tracking, confidence scoring,
and multi-hypothesis fault reports. Faults are never claimed as confirmed
unless supported by explicit equipment diagnostics.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, DateTime, Float, Index, String

from app.models.equipment import Base, JSON_TYPE
from app.models.health import DataQuality


# ── Pydantic Domain Models ───────────────────────────────────────────

class FaultHypothesis(BaseModel):
    """
    A single fault hypothesis with evidence and confidence.

    Confidence is derived from:
    - Number of supporting signals
    - Signal quality
    - Pattern match strength vs known fault signatures
    Confidence is never fabricated without evidence.
    """
    fault: str = Field(
        ...,
        description="Fault classification label (e.g. TURBINE_ICING, SENSOR_ERROR)",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Confidence in this hypothesis (0=speculative, 1=high confidence)",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Supporting evidence signals and observations",
    )
    description: str = Field(
        default="",
        description="Human-readable fault description",
    )
    recommended_investigation: str = Field(
        default="",
        description="Suggested investigation action (informational only)",
    )
    is_confirmed: bool = Field(
        default=False,
        description="True only with explicit equipment diagnostic confirmation",
    )


class FaultReport(BaseModel):
    """Multi-hypothesis fault report for an equipment asset."""
    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    equipment_id: str = Field(..., description="Assessed equipment")
    station_id: str = Field(..., description="Station identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    hypotheses: list[FaultHypothesis] = Field(
        default_factory=list,
        description="Ranked fault hypotheses (highest confidence first)",
    )
    data_quality: DataQuality = Field(default=DataQuality.GOOD)
    primary_fault: str | None = Field(
        default=None,
        description="Highest-confidence fault if any exceed threshold",
    )
    sensor_fault_suspected: bool = Field(
        default=False,
        description="True if evidence suggests sensor rather than equipment fault",
    )

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    def get_top_hypothesis(self) -> FaultHypothesis | None:
        """Return highest confidence hypothesis, or None."""
        if not self.hypotheses:
            return None
        return max(self.hypotheses, key=lambda h: h.confidence)


# ── SQLAlchemy ORM Model ─────────────────────────────────────────────

class FaultRecord(Base):
    """Persistent fault hypothesis record."""

    __tablename__ = "fault_hypotheses"

    record_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    equipment_id = Column(String(100), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    hypotheses_json = Column(JSON_TYPE, nullable=False, default=[])
    primary_fault = Column(String(100), nullable=True)
    primary_confidence = Column(Float, nullable=True)
    data_quality = Column(String(20), nullable=False, default="GOOD")
    sensor_fault_suspected = Column(String(10), nullable=False, default="false")
    metadata_json = Column(JSON_TYPE, nullable=False, default={})

    __table_args__ = (
        Index("ix_faults_equipment_ts", "equipment_id", "timestamp"),
    )

    def to_domain(self) -> FaultReport:
        """Convert ORM record to domain FaultReport."""
        return FaultReport(
            report_id=self.record_id,
            equipment_id=self.equipment_id,
            station_id=self.station_id,
            timestamp=self.timestamp,
            hypotheses=[FaultHypothesis(**h) for h in (self.hypotheses_json or [])],
            data_quality=DataQuality(self.data_quality),
            primary_fault=self.primary_fault,
            sensor_fault_suspected=self.sensor_fault_suspected == "true",
        )

    @classmethod
    def from_domain(cls, r: FaultReport) -> "FaultRecord":
        """Create ORM record from domain FaultReport."""
        top = r.get_top_hypothesis()
        return cls(
            record_id=r.report_id,
            equipment_id=r.equipment_id,
            station_id=r.station_id,
            timestamp=r.timestamp,
            hypotheses_json=[h.model_dump() for h in r.hypotheses],
            primary_fault=r.primary_fault or (top.fault if top else None),
            primary_confidence=top.confidence if top else None,
            data_quality=r.data_quality.value,
            sensor_fault_suspected="true" if r.sensor_fault_suspected else "false",
        )
