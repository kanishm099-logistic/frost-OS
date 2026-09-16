"""
Frost OS Module 05 — Anomaly Domain & ORM Models.

Defines anomaly detection result types, severity levels, confidence tracking,
and persistent anomaly records for diagnostic analysis.
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

class AnomalySeverity(str, enum.Enum):
    """Anomaly severity classification."""
    INFO = "INFO"            # Informational, no action needed
    LOW = "LOW"              # Minor deviation, track over time
    MEDIUM = "MEDIUM"        # Notable deviation, warrants investigation
    HIGH = "HIGH"            # Significant anomaly, likely issue
    CRITICAL = "CRITICAL"    # Severe anomaly, immediate attention needed


class AnomalyType(str, enum.Enum):
    """Classification of how the anomaly was detected."""
    LIMIT_VIOLATION = "LIMIT_VIOLATION"        # Deterministic hard limit breach
    RATE_OF_CHANGE = "RATE_OF_CHANGE"          # Implausible rate of change
    RESIDUAL_DEVIATION = "RESIDUAL_DEVIATION"  # Actual vs expected deviation
    STATISTICAL = "STATISTICAL"                # Z-score, IQR, EWMA detection
    ML_DETECTED = "ML_DETECTED"                # Isolation Forest / ML model
    SENSOR_FAULT = "SENSOR_FAULT"              # Stale, noisy, or disagreeing sensor
    CORRELATION = "CORRELATION"                # Multi-signal correlated anomaly


class AnomalyStatus(str, enum.Enum):
    """Lifecycle status of a detected anomaly."""
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


# ── Pydantic Domain Models ───────────────────────────────────────────

class Anomaly(BaseModel):
    """
    Single anomaly detection result with evidence and confidence.

    Score meaning (documented):
    - 0.0-0.3: Minor deviation, within normal variance
    - 0.3-0.6: Notable deviation, warrants monitoring
    - 0.6-0.8: Significant anomaly, investigation recommended
    - 0.8-1.0: Severe anomaly, strong evidence of issue
    """
    anomaly_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    equipment_id: str = Field(..., description="Affected equipment asset")
    station_id: str = Field(..., description="Station identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    type: AnomalyType = Field(..., description="Detection method used")
    severity: AnomalySeverity = Field(default=AnomalySeverity.LOW)
    score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Anomaly score: 0=normal, 1=extreme anomaly",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Detection confidence: 0=uncertain, 1=highly confident",
    )
    observed_value: float | None = Field(default=None, description="Measured value")
    expected_value: float | None = Field(default=None, description="Expected normal value")
    residual: float | None = Field(default=None, description="Observed − expected")
    signals: list[str] = Field(
        default_factory=list,
        description="Contributing signal/metric names",
    )
    possible_causes: list[str] = Field(
        default_factory=list,
        description="Potential root causes for the anomaly",
    )
    status: AnomalyStatus = Field(default=AnomalyStatus.ACTIVE)
    detection_layer: str = Field(
        default="", description="Which detection layer flagged this",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    @property
    def is_critical(self) -> bool:
        return self.severity == AnomalySeverity.CRITICAL

    @property
    def has_evidence(self) -> bool:
        return len(self.signals) > 0 or self.residual is not None


# ── SQLAlchemy ORM Model ─────────────────────────────────────────────

class AnomalyRecord(Base):
    """Persistent anomaly detection record."""

    __tablename__ = "anomalies"

    anomaly_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    equipment_id = Column(String(100), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    anomaly_type = Column(
        SQLEnum(AnomalyType, name="anomaly_type_enum"),
        nullable=False, index=True,
    )
    severity = Column(
        SQLEnum(AnomalySeverity, name="anomaly_severity_enum"),
        nullable=False, index=True,
    )
    score = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.0)
    observed_value = Column(Float, nullable=True)
    expected_value = Column(Float, nullable=True)
    residual = Column(Float, nullable=True)
    signals_json = Column(JSON_TYPE, nullable=False, default=[])
    possible_causes_json = Column(JSON_TYPE, nullable=False, default=[])
    status = Column(
        SQLEnum(AnomalyStatus, name="anomaly_status_enum"),
        nullable=False, default="ACTIVE",
    )
    detection_layer = Column(String(50), nullable=False, default="")
    metadata_json = Column(JSON_TYPE, nullable=False, default={})

    __table_args__ = (
        Index("ix_anomalies_equipment_ts", "equipment_id", "timestamp"),
        Index("ix_anomalies_station_severity", "station_id", "severity"),
    )

    def to_domain(self) -> Anomaly:
        """Convert ORM record to domain Anomaly."""
        return Anomaly(
            anomaly_id=self.anomaly_id,
            equipment_id=self.equipment_id,
            station_id=self.station_id,
            timestamp=self.timestamp,
            type=self.anomaly_type,
            severity=self.severity,
            score=self.score,
            confidence=self.confidence,
            observed_value=self.observed_value,
            expected_value=self.expected_value,
            residual=self.residual,
            signals=self.signals_json or [],
            possible_causes=self.possible_causes_json or [],
            status=self.status,
            detection_layer=self.detection_layer,
            metadata=self.metadata_json or {},
        )

    @classmethod
    def from_domain(cls, a: Anomaly) -> "AnomalyRecord":
        """Create ORM record from domain Anomaly."""
        return cls(
            anomaly_id=a.anomaly_id,
            equipment_id=a.equipment_id,
            station_id=a.station_id,
            timestamp=a.timestamp,
            anomaly_type=a.type,
            severity=a.severity,
            score=a.score,
            confidence=a.confidence,
            observed_value=a.observed_value,
            expected_value=a.expected_value,
            residual=a.residual,
            signals_json=a.signals,
            possible_causes_json=a.possible_causes,
            status=a.status,
            detection_layer=a.detection_layer,
            metadata_json=a.metadata,
        )
