"""
Frost OS Module 05 — Equipment Diagnostic Adapter Base.

Abstract base class for equipment-specific diagnostic adapters. Each adapter
implements domain-specific physics models, rule checks, expected behavior
computation, and fault signature definitions.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

from app.models.anomaly import Anomaly
from app.models.equipment import Equipment, OperatingBaseline
from app.models.fault import FaultHypothesis


@dataclass
class SignalData:
    """Time series data for a single signal/metric."""
    name: str
    values: np.ndarray
    timestamps: list[datetime]
    unit: str = ""
    quality: str = "GOOD"

    @property
    def latest(self) -> float:
        """Most recent value."""
        if len(self.values) == 0:
            return float("nan")
        return float(self.values[-1])

    @property
    def mean(self) -> float:
        if len(self.values) == 0:
            return float("nan")
        return float(np.nanmean(self.values))

    @property
    def std(self) -> float:
        if len(self.values) < 2:
            return 0.0
        return float(np.nanstd(self.values))

    @property
    def count(self) -> int:
        return len(self.values)

    def is_empty(self) -> bool:
        return len(self.values) == 0


@dataclass
class TelemetryWindow:
    """
    Windowed telemetry data for a single equipment asset.

    Contains time-aligned signals for the diagnostic analysis window.
    """
    equipment_id: str
    station_id: str
    signals: dict[str, SignalData] = field(default_factory=dict)
    window_start: datetime | None = None
    window_end: datetime | None = None
    data_quality: str = "GOOD"

    def get_signal(self, name: str) -> SignalData | None:
        """Get signal by name, returns None if not available."""
        return self.signals.get(name)

    def has_signal(self, name: str) -> bool:
        """Check if a signal exists and has data."""
        sig = self.signals.get(name)
        return sig is not None and not sig.is_empty()

    def has_signals(self, *names: str) -> bool:
        """Check if all listed signals exist and have data."""
        return all(self.has_signal(n) for n in names)

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    @property
    def available_signals(self) -> list[str]:
        return [k for k, v in self.signals.items() if not v.is_empty()]


@dataclass
class FeatureVector:
    """Extracted features for anomaly/fault detection."""
    equipment_id: str
    timestamp: datetime
    features: dict[str, float] = field(default_factory=dict)
    feature_names: list[str] = field(default_factory=list)

    def to_array(self) -> np.ndarray:
        """Convert to numpy array in consistent feature order."""
        return np.array([self.features.get(n, 0.0) for n in self.feature_names])


@dataclass
class RuleCheckResult:
    """Result from equipment-specific rule checks."""
    anomalies: list[Anomaly] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    signals_checked: list[str] = field(default_factory=list)

    @property
    def has_anomalies(self) -> bool:
        return len(self.anomalies) > 0


@dataclass
class ExpectedBehavior:
    """Expected equipment behavior under current conditions."""
    expected_values: dict[str, float] = field(default_factory=dict)
    conditions: dict[str, float] = field(default_factory=dict)
    model_type: str = "physics"  # physics, statistical, or ml
    confidence: float = 1.0


class EquipmentDiagnosticAdapter(abc.ABC):
    """
    Abstract base class for equipment-specific diagnostic logic.

    Each concrete adapter implements domain-specific physics models,
    operating rules, expected behavior computation, and known fault
    signatures for a specific equipment type.
    """

    @abc.abstractmethod
    def extract_features(
        self,
        window: TelemetryWindow,
        baseline: OperatingBaseline | None = None,
    ) -> FeatureVector:
        """
        Extract diagnostic features from telemetry window.

        Returns a FeatureVector with named features suitable for
        anomaly detection and fault classification.
        """
        ...

    @abc.abstractmethod
    def check_rules(
        self,
        window: TelemetryWindow,
        equipment: Equipment,
        baseline: OperatingBaseline | None = None,
    ) -> RuleCheckResult:
        """
        Apply deterministic rule checks specific to this equipment type.

        Checks operating limits, rate of change limits, and known
        physics-based constraints. Returns anomalies for violations.
        """
        ...

    @abc.abstractmethod
    def compute_expected(
        self,
        conditions: dict[str, float],
        equipment: Equipment,
    ) -> ExpectedBehavior:
        """
        Compute expected equipment behavior under given conditions.

        Uses physics models, power curves, efficiency models, or
        statistical baselines to determine what the equipment should
        be doing under current operating conditions.
        """
        ...

    @abc.abstractmethod
    def get_fault_signatures(self) -> dict[str, dict[str, Any]]:
        """
        Return known fault signatures for this equipment type.

        Each signature maps a fault label to required evidence patterns:
        {
            "FAULT_NAME": {
                "required_signals": ["signal_a", "signal_b"],
                "conditions": {"signal_a": "high", "signal_b": "low"},
                "description": "Human readable fault description",
                "min_evidence_count": 2,
            }
        }
        """
        ...

    def get_default_limits(self) -> dict[str, tuple[float, float]]:
        """
        Return default operating limits for this equipment type.

        Override in concrete adapters to provide equipment-specific defaults.
        Returns dict of metric_name -> (min_value, max_value).
        """
        return {}
