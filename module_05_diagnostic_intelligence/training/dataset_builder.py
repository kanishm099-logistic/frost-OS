"""
Frost OS Module 05 — Training Dataset Builder.

Builds labeled datasets from historical telemetry for
anomaly detection and fault classification model training.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import structlog

from app.core.diagnostic_engine import DiagnosticEngine
from app.demo.simulator import DiagnosticSimulator

logger = structlog.get_logger(__name__)


def build_wind_turbine_dataset(
    num_normal: int = 500,
    num_icing: int = 100,
    num_bearing: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    """
    Build labeled dataset for wind turbine anomaly detection.

    Returns:
        {
            "features": np.ndarray (N x F),
            "labels": np.ndarray (N,) — 0=normal, 1=icing, 2=bearing_wear
            "feature_names": list[str],
        }
    """
    from app.config.settings import Settings
    from app.equipment.wind import WindTurbineAdapter
    from app.models.equipment import Equipment, EquipmentType, OperatingLimits, OperatingBaseline
    from app.core.telemetry_processor import TelemetryProcessor

    settings = Settings(environment="testing", mock_mode=True)
    sim = DiagnosticSimulator(seed=seed)
    adapter = WindTurbineAdapter()
    processor = TelemetryProcessor(settings)

    equipment = Equipment(
        equipment_id="WT-TRAIN",
        station_id="TRAIN-STATION",
        type=EquipmentType.WIND_TURBINE,
        rated_power_kw=120.0,
        operating_limits=OperatingLimits(max_vibration=8.0, max_temperature_c=80.0),
    )

    all_features: list[np.ndarray] = []
    all_labels: list[int] = []
    feature_names: list[str] = []

    scenarios = [
        ("normal", num_normal, 0),
        ("icing", num_icing, 1),
        ("bearing_wear", num_bearing, 2),
    ]

    for scenario, count, label in scenarios:
        for _ in range(count):
            readings = sim.generate_wind_telemetry(
                num_readings=20,
                scenario=scenario,
            )
            window = processor.ingest_batch("WT-TRAIN", "TRAIN-STATION", readings)
            fv = adapter.extract_features(window)

            if not feature_names:
                feature_names = fv.feature_names

            all_features.append(fv.to_array())
            all_labels.append(label)
            processor.clear_buffer("WT-TRAIN")

    return {
        "features": np.array(all_features),
        "labels": np.array(all_labels),
        "feature_names": feature_names,
        "label_names": {0: "normal", 1: "icing", 2: "bearing_wear"},
    }


def build_battery_dataset(
    num_normal: int = 500,
    num_thermal: int = 100,
    seed: int = 42,
) -> dict[str, Any]:
    """Build labeled dataset for battery anomaly detection."""
    from app.config.settings import Settings
    from app.equipment.battery import BatteryDiagnosticAdapter
    from app.models.equipment import Equipment, EquipmentType
    from app.core.telemetry_processor import TelemetryProcessor

    settings = Settings(environment="testing", mock_mode=True)
    sim = DiagnosticSimulator(seed=seed)
    adapter = BatteryDiagnosticAdapter()
    processor = TelemetryProcessor(settings)

    equipment = Equipment(
        equipment_id="BAT-TRAIN",
        station_id="TRAIN-STATION",
        type=EquipmentType.BATTERY,
        capacity=6000.0,
    )

    all_features: list[np.ndarray] = []
    all_labels: list[int] = []
    feature_names: list[str] = []

    for scenario, count, label in [("normal", num_normal, 0), ("thermal_stress", num_thermal, 1)]:
        for _ in range(count):
            readings = sim.generate_battery_telemetry(num_readings=20, scenario=scenario)
            window = processor.ingest_batch("BAT-TRAIN", "TRAIN-STATION", readings)
            fv = adapter.extract_features(window)
            if not feature_names:
                feature_names = fv.feature_names
            all_features.append(fv.to_array())
            all_labels.append(label)
            processor.clear_buffer("BAT-TRAIN")

    return {
        "features": np.array(all_features),
        "labels": np.array(all_labels),
        "feature_names": feature_names,
        "label_names": {0: "normal", 1: "thermal_stress"},
    }


if __name__ == "__main__":
    print("Building wind turbine dataset...")
    wind_data = build_wind_turbine_dataset()
    print(f"  Features: {wind_data['features'].shape}")
    print(f"  Labels: {np.bincount(wind_data['labels'])}")

    print("\nBuilding battery dataset...")
    bat_data = build_battery_dataset()
    print(f"  Features: {bat_data['features'].shape}")
    print(f"  Labels: {np.bincount(bat_data['labels'])}")
