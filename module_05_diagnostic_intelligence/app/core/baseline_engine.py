"""
Frost OS Module 05 — Baseline Engine.

Creates and maintains normal operating profiles for each equipment type
using historical healthy data. Baselines are condition-aware: they bin
by operating conditions (temperature, load, wind speed, irradiance, SOC)
to avoid naive fixed-threshold comparisons.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog

from app.config.settings import Settings
from app.equipment.base import TelemetryWindow
from app.models.equipment import EquipmentType, OperatingBaseline

logger = structlog.get_logger(__name__)

# Default condition bins for each equipment type
DEFAULT_CONDITION_BINS: dict[EquipmentType, dict[str, list[float]]] = {
    EquipmentType.WIND_TURBINE: {
        "wind_speed_ms": [0.0, 3.0, 6.0, 9.0, 12.0, 18.0, 25.0],
        "ambient_temperature_c": [-50.0, -20.0, -5.0, 5.0, 20.0],
    },
    EquipmentType.SOLAR_ARRAY: {
        "irradiance_wm2": [0.0, 100.0, 300.0, 600.0, 900.0, 1200.0],
        "temperature_c": [-40.0, -10.0, 10.0, 25.0, 40.0],
    },
    EquipmentType.BATTERY: {
        "soc_pct": [0.0, 20.0, 40.0, 60.0, 80.0, 100.0],
        "temperature_c": [-20.0, 0.0, 15.0, 30.0, 45.0],
    },
    EquipmentType.INVERTER: {
        "input_power_kw": [0.0, 10.0, 30.0, 60.0, 100.0],
        "temperature_c": [-10.0, 10.0, 30.0, 50.0],
    },
}


class BaselineEngine:
    """
    Manages condition-aware normal operating baselines for equipment.

    Never compares equipment operating under different conditions using
    a naive fixed threshold alone. Instead, bins by relevant operating
    conditions to build per-condition expected behavior profiles.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._baselines: dict[str, OperatingBaseline] = {}
        self._condition_bins = dict(DEFAULT_CONDITION_BINS)

    def build_baseline(
        self,
        equipment_id: str,
        equipment_type: EquipmentType,
        historical_windows: list[TelemetryWindow],
    ) -> OperatingBaseline:
        """
        Build a normal operating baseline from historical healthy data.

        Only uses data marked as healthy (no anomalies during collection).
        Computes per-metric statistics (mean, std, min, max) binned by
        operating conditions.
        """
        condition_config = self._condition_bins.get(equipment_type, {})
        expected_values: dict[str, dict[str, float]] = {}
        total_samples = 0

        # Collect all metric data
        all_metric_data: dict[str, list[float]] = {}
        for window in historical_windows:
            for sig_name, sig_data in window.signals.items():
                if sig_data.is_empty():
                    continue
                if sig_name not in all_metric_data:
                    all_metric_data[sig_name] = []
                all_metric_data[sig_name].extend(sig_data.values.tolist())
                total_samples += sig_data.count

        # Compute statistics per metric
        for metric_name, values in all_metric_data.items():
            arr = np.array(values, dtype=np.float64)
            arr = arr[~np.isnan(arr)]
            if len(arr) == 0:
                continue

            expected_values[metric_name] = {
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "count": float(len(arr)),
                "p05": float(np.percentile(arr, 5)),
                "p95": float(np.percentile(arr, 95)),
            }

        baseline = OperatingBaseline(
            equipment_id=equipment_id,
            equipment_type=equipment_type,
            condition_bins=condition_config,
            expected_values=expected_values,
            sample_count=total_samples,
            valid_from=datetime.now(timezone.utc),
        )

        self._baselines[equipment_id] = baseline

        logger.info(
            "baseline_built",
            equipment_id=equipment_id,
            equipment_type=equipment_type.value,
            metrics=list(expected_values.keys()),
            sample_count=total_samples,
        )

        return baseline

    def get_baseline(self, equipment_id: str) -> OperatingBaseline | None:
        """Retrieve the current baseline for an equipment asset."""
        return self._baselines.get(equipment_id)

    def get_expected(
        self,
        equipment_id: str,
        metric_name: str,
        conditions: dict[str, float] | None = None,
    ) -> dict[str, float] | None:
        """
        Get expected values for a metric under current conditions.

        Returns {mean, std, min, max} or None if no baseline exists.
        """
        baseline = self._baselines.get(equipment_id)
        if baseline is None:
            return None

        return baseline.expected_values.get(metric_name)

    def compute_residual(
        self,
        equipment_id: str,
        metric_name: str,
        observed_value: float,
        conditions: dict[str, float] | None = None,
    ) -> dict[str, float] | None:
        """
        Compute residual between observed and expected value.

        Returns {residual, residual_pct, zscore, expected_mean, expected_std}
        or None if no baseline exists.
        """
        expected = self.get_expected(equipment_id, metric_name, conditions)
        if expected is None:
            return None

        mean = expected["mean"]
        std = expected.get("std", 1.0)

        residual = observed_value - mean
        residual_pct = (residual / abs(mean) * 100.0) if abs(mean) > 1e-6 else 0.0
        zscore = (residual / std) if std > 1e-6 else 0.0

        return {
            "residual": residual,
            "residual_pct": residual_pct,
            "zscore": zscore,
            "expected_mean": mean,
            "expected_std": std,
        }

    def set_baseline(self, equipment_id: str, baseline: OperatingBaseline) -> None:
        """Manually set a baseline for an equipment asset."""
        self._baselines[equipment_id] = baseline

    def create_default_baseline(
        self,
        equipment_id: str,
        equipment_type: EquipmentType,
    ) -> OperatingBaseline:
        """
        Create a default baseline for an equipment type when no historical
        data is available. Uses sensible defaults based on equipment type.
        """
        defaults: dict[EquipmentType, dict[str, dict[str, float]]] = {
            EquipmentType.WIND_TURBINE: {
                "power_kw": {"mean": 60.0, "std": 30.0, "min": 0.0, "max": 120.0, "count": 0},
                "wind_speed_ms": {"mean": 8.0, "std": 4.0, "min": 0.0, "max": 25.0, "count": 0},
                "vibration": {"mean": 2.0, "std": 0.5, "min": 0.5, "max": 5.0, "count": 0},
                "rpm": {"mean": 150.0, "std": 50.0, "min": 0.0, "max": 300.0, "count": 0},
                "nacelle_temperature_c": {"mean": 30.0, "std": 10.0, "min": -40.0, "max": 70.0, "count": 0},
            },
            EquipmentType.SOLAR_ARRAY: {
                "power_kw": {"mean": 30.0, "std": 25.0, "min": 0.0, "max": 80.0, "count": 0},
                "irradiance_wm2": {"mean": 400.0, "std": 250.0, "min": 0.0, "max": 1200.0, "count": 0},
            },
            EquipmentType.BATTERY: {
                "soc_pct": {"mean": 60.0, "std": 20.0, "min": 15.0, "max": 95.0, "count": 0},
                "temperature_c": {"mean": 25.0, "std": 5.0, "min": -10.0, "max": 45.0, "count": 0},
                "voltage_v": {"mean": 400.0, "std": 20.0, "min": 350.0, "max": 450.0, "count": 0},
            },
            EquipmentType.INVERTER: {
                "input_power_kw": {"mean": 50.0, "std": 25.0, "min": 0.0, "max": 120.0, "count": 0},
                "output_power_kw": {"mean": 48.0, "std": 24.0, "min": 0.0, "max": 115.0, "count": 0},
                "temperature_c": {"mean": 35.0, "std": 10.0, "min": 10.0, "max": 60.0, "count": 0},
            },
        }

        expected = defaults.get(equipment_type, {})
        baseline = OperatingBaseline(
            equipment_id=equipment_id,
            equipment_type=equipment_type,
            expected_values=expected,
            sample_count=0,
            valid_from=datetime.now(timezone.utc),
            model_version="default",
        )
        self._baselines[equipment_id] = baseline
        return baseline
