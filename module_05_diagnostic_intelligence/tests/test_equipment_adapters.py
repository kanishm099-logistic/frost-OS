"""
Frost OS Module 05 — Equipment Adapter Tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from app.equipment.base import SignalData, TelemetryWindow
from app.equipment.wind import WindTurbineAdapter
from app.equipment.solar import SolarArrayAdapter
from app.equipment.battery import BatteryDiagnosticAdapter
from app.equipment.sensor import SensorDiagnosticAdapter
from app.models.equipment import Equipment, EquipmentType, OperatingLimits


def _make_window(equipment_id: str, signals_data: dict[str, list[float]]) -> TelemetryWindow:
    """Helper to build a TelemetryWindow."""
    now = datetime.now(timezone.utc)
    signals = {}
    for name, values in signals_data.items():
        timestamps = [now - timedelta(seconds=(len(values) - i) * 5) for i in range(len(values))]
        signals[name] = SignalData(name=name, values=np.array(values), timestamps=timestamps)
    return TelemetryWindow(
        equipment_id=equipment_id,
        station_id="TEST-STATION",
        signals=signals,
        window_start=now - timedelta(seconds=100),
        window_end=now,
    )


class TestWindTurbineAdapter:
    """Tests for WindTurbineAdapter."""

    def setup_method(self):
        self.adapter = WindTurbineAdapter(
            rated_power_kw=120.0,
            cut_in_speed_ms=3.0,
            rated_speed_ms=12.0,
            cut_out_speed_ms=25.0,
        )
        self.equipment = Equipment(
            equipment_id="WT-TEST",
            station_id="TEST-STATION",
            type=EquipmentType.WIND_TURBINE,
            rated_power_kw=120.0,
            operating_limits=OperatingLimits(max_vibration=8.0, max_temperature_c=80.0),
        )

    def test_power_curve_zero_below_cutin(self):
        assert self.adapter.power_curve(2.0) == 0.0

    def test_power_curve_zero_above_cutout(self):
        assert self.adapter.power_curve(30.0) == 0.0

    def test_power_curve_rated_at_rated_speed(self):
        assert self.adapter.power_curve(12.0) == 120.0

    def test_power_curve_cubic_in_partial(self):
        power = self.adapter.power_curve(7.0)
        assert 0 < power < 120.0

    def test_extract_features_produces_named_features(self):
        window = _make_window("WT-TEST", {
            "power_kw": [50.0] * 20,
            "wind_speed_ms": [8.0] * 20,
            "vibration": [2.0] * 20,
            "rpm": [150.0] * 20,
            "nacelle_temperature_c": [35.0] * 20,
            "ambient_temperature_c": [-10.0] * 20,
        })
        features = self.adapter.extract_features(window)
        assert "power_kw_mean" in features.features
        assert "power_curve_residual" in features.features
        assert "icing_indicator" in features.features

    def test_rule_check_detects_vibration_limit(self):
        window = _make_window("WT-TEST", {
            "power_kw": [50.0] * 20,
            "wind_speed_ms": [8.0] * 20,
            "vibration": [12.0] * 20,  # Above max_vibration=8.0
            "rpm": [150.0] * 20,
        })
        result = self.adapter.check_rules(window, self.equipment)
        assert result.has_anomalies
        vib_anomalies = [a for a in result.anomalies if "vibration" in a.signals]
        assert len(vib_anomalies) > 0

    def test_fault_signatures_defined(self):
        sigs = self.adapter.get_fault_signatures()
        assert "TURBINE_ICING" in sigs
        assert "BLADE_DAMAGE" in sigs
        assert "GEARBOX_WEAR" in sigs


class TestSolarArrayAdapter:
    """Tests for SolarArrayAdapter."""

    def setup_method(self):
        self.adapter = SolarArrayAdapter(
            installed_capacity_kw=80.0,
            panel_efficiency=0.19,
            panel_area_m2=420.0,
        )
        self.equipment = Equipment(
            equipment_id="SA-TEST",
            station_id="TEST-STATION",
            type=EquipmentType.SOLAR_ARRAY,
            rated_power_kw=80.0,
        )

    def test_expected_generation_zero_at_night(self):
        assert self.adapter.expected_generation(0.0) == 0.0

    def test_expected_generation_positive_with_irradiance(self):
        power = self.adapter.expected_generation(600.0, 25.0)
        assert power > 0.0
        assert power <= 80.0

    def test_temperature_derating(self):
        power_25c = self.adapter.expected_generation(600.0, 25.0)
        power_45c = self.adapter.expected_generation(600.0, 45.0)
        assert power_45c < power_25c  # Higher temp = lower output

    def test_fault_signatures_defined(self):
        sigs = self.adapter.get_fault_signatures()
        assert "PANEL_DEGRADATION" in sigs
        assert "INVERTER_FAULT" in sigs


class TestBatteryAdapter:
    """Tests for BatteryDiagnosticAdapter."""

    def setup_method(self):
        self.adapter = BatteryDiagnosticAdapter(
            capacity_kwh=6000.0,
            temp_high_c=45.0,
            temp_critical_c=55.0,
        )
        self.equipment = Equipment(
            equipment_id="BAT-TEST",
            station_id="TEST-STATION",
            type=EquipmentType.BATTERY,
            capacity=6000.0,
        )

    def test_no_anomaly_for_normal_temp(self):
        window = _make_window("BAT-TEST", {
            "temperature_c": [25.0] * 20,
            "soc_pct": [65.0] * 20,
        })
        result = self.adapter.check_rules(window, self.equipment)
        # Should not have temperature anomalies
        temp_anomalies = [a for a in result.anomalies if "temperature_c" in a.signals]
        assert len(temp_anomalies) == 0

    def test_detects_high_temperature(self):
        window = _make_window("BAT-TEST", {
            "temperature_c": [50.0] * 20,  # Above temp_high_c=45
            "soc_pct": [65.0] * 20,
        })
        result = self.adapter.check_rules(window, self.equipment)
        temp_anomalies = [a for a in result.anomalies if "temperature_c" in a.signals]
        assert len(temp_anomalies) > 0

    def test_critical_temp_requires_corroboration(self):
        """Critical temperature should only be CRITICAL with correlated evidence."""
        # Single high reading — should NOT be CRITICAL
        window = _make_window("BAT-TEST", {
            "temperature_c": [25.0] * 19 + [60.0],  # Single spike
            "soc_pct": [65.0] * 20,
        })
        result = self.adapter.check_rules(window, self.equipment)
        critical_anomalies = [
            a for a in result.anomalies
            if a.severity.value == "CRITICAL"
        ]
        assert len(critical_anomalies) == 0  # Single reading → not escalated


class TestSensorAdapter:
    """Tests for SensorDiagnosticAdapter."""

    def setup_method(self):
        self.adapter = SensorDiagnosticAdapter(
            stale_threshold_seconds=60.0,
            constant_value_window=10,
            noise_spike_zscore=5.0,
        )
        self.equipment = Equipment(
            equipment_id="SENS-TEST",
            station_id="TEST-STATION",
            type=EquipmentType.SENSOR,
        )

    def test_detects_empty_signal(self):
        window = TelemetryWindow(
            equipment_id="SENS-TEST",
            station_id="TEST-STATION",
            signals={
                "power_kw": SignalData(name="power_kw", values=np.array([]), timestamps=[]),
            },
        )
        result = self.adapter.check_rules(window, self.equipment)
        assert result.has_anomalies

    def test_detects_constant_value(self):
        window = _make_window("SENS-TEST", {
            "power_kw": [42.0] * 20,  # Perfectly constant
        })
        result = self.adapter.check_rules(window, self.equipment)
        constant_anomalies = [
            a for a in result.anomalies
            if a.metadata.get("issue") == "constant_value"
        ]
        assert len(constant_anomalies) > 0
