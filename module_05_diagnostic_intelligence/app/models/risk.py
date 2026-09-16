"""
Frost OS Module 05 — Failure Risk Domain & ORM Models.

Defines failure risk estimation over configurable time horizons with
explicit data sufficiency requirements. Returns UNKNOWN rather than
fabricating probabilities when data is insufficient.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, DateTime, Float, Index, String

from app.models.equipment import Base, JSON_TYPE


# ── Enumerations ──────────────────────────────────────────────────────

class RiskLevel(str, enum.Enum):
    """Failure risk classification."""
    NEGLIGIBLE = "NEGLIGIBLE"  # < 5% probability
    LOW = "LOW"                # 5-15% probability
    MODERATE = "MODERATE"      # 15-35% probability
    HIGH = "HIGH"              # 35-65% probability
    CRITICAL = "CRITICAL"      # > 65% probability
    UNKNOWN = "UNKNOWN"        # Insufficient data to estimate


class DataSufficiency(str, enum.Enum):
    """Data availability for risk estimation."""
    SUFFICIENT = "SUFFICIENT"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


# ── Pydantic Domain Models ───────────────────────────────────────────

class RiskHorizon(BaseModel):
    """Failure risk estimate for a single time horizon."""
    horizon_label: str = Field(
        ..., description="Human-readable horizon (e.g. '1h', '24h', '7d')",
    )
    horizon_hours: float = Field(..., ge=0.0, description="Horizon in hours")
    probability: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Estimated failure probability (None if insufficient data)",
    )
    risk_level: RiskLevel = Field(default=RiskLevel.UNKNOWN)
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Confidence in the risk estimate",
    )


class FailureRisk(BaseModel):
    """
    Complete failure risk assessment for an equipment asset.

    Risk is estimated using exponential hazard models scaled by health severity.
    When data is insufficient, returns UNKNOWN/INSUFFICIENT_DATA rather
    than inventing probability values.
    """
    risk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    equipment_id: str = Field(..., description="Assessed equipment")
    station_id: str = Field(..., description="Station identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    horizons: dict[str, RiskHorizon] = Field(
        default_factory=dict,
        description="Risk estimates per time horizon",
    )
    overall_risk_level: RiskLevel = Field(default=RiskLevel.UNKNOWN)
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Overall confidence in risk assessment",
    )
    data_sufficiency: DataSufficiency = Field(
        default=DataSufficiency.INSUFFICIENT,
        description="Whether enough data exists for meaningful estimation",
    )
    model_version: str = Field(default="v0.1.0")
    contributing_factors: list[str] = Field(
        default_factory=list,
        description="Factors driving risk estimate (health, anomalies, degradation)",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> Any:
        if isinstance(v, datetime) and v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ── SQLAlchemy ORM Model ─────────────────────────────────────────────

class FailureRiskRecord(Base):
    """Persistent failure risk estimate."""

    __tablename__ = "failure_risks"

    risk_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    equipment_id = Column(String(100), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    overall_risk_level = Column(String(20), nullable=False, default="UNKNOWN")
    confidence = Column(Float, nullable=False, default=0.0)
    data_sufficiency = Column(String(20), nullable=False, default="INSUFFICIENT")
    horizons_json = Column(JSON_TYPE, nullable=False, default={})
    contributing_factors_json = Column(JSON_TYPE, nullable=False, default=[])
    model_version = Column(String(50), nullable=False, default="v0.1.0")
    metadata_json = Column(JSON_TYPE, nullable=False, default={})

    __table_args__ = (
        Index("ix_risk_equipment_ts", "equipment_id", "timestamp"),
    )

    def to_domain(self) -> FailureRisk:
        """Convert ORM record to domain FailureRisk."""
        horizons = {}
        for key, val in (self.horizons_json or {}).items():
            horizons[key] = RiskHorizon(**val)
        return FailureRisk(
            risk_id=self.risk_id,
            equipment_id=self.equipment_id,
            station_id=self.station_id,
            timestamp=self.timestamp,
            horizons=horizons,
            overall_risk_level=RiskLevel(self.overall_risk_level),
            confidence=self.confidence,
            data_sufficiency=DataSufficiency(self.data_sufficiency),
            model_version=self.model_version,
            contributing_factors=self.contributing_factors_json or [],
            metadata=self.metadata_json or {},
        )

    @classmethod
    def from_domain(cls, r: FailureRisk) -> "FailureRiskRecord":
        """Create ORM record from domain FailureRisk."""
        return cls(
            risk_id=r.risk_id,
            equipment_id=r.equipment_id,
            station_id=r.station_id,
            timestamp=r.timestamp,
            overall_risk_level=r.overall_risk_level.value,
            confidence=r.confidence,
            data_sufficiency=r.data_sufficiency.value,
            horizons_json={k: v.model_dump() for k, v in r.horizons.items()},
            contributing_factors_json=r.contributing_factors,
            model_version=r.model_version,
            metadata_json=r.metadata,
        )


class DegradationTrendRecord(Base):
    """Persistent equipment degradation trend tracking."""

    __tablename__ = "degradation_trends"

    trend_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    equipment_id = Column(String(100), nullable=False, index=True)
    station_id = Column(String(100), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    metric_name = Column(String(100), nullable=False)
    current_value = Column(Float, nullable=True)
    baseline_value = Column(Float, nullable=True)
    degradation_rate_per_month = Column(Float, nullable=True)
    trend_direction = Column(String(20), nullable=False, default="stable")
    confidence = Column(Float, nullable=False, default=0.0)
    window_days = Column(Float, nullable=False, default=30.0)
    metadata_json = Column(JSON_TYPE, nullable=False, default={})

    __table_args__ = (
        Index("ix_degradation_equipment_ts", "equipment_id", "timestamp"),
    )
