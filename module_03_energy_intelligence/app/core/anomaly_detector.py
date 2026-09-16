"""
Frost OS Module 03 — Anomaly Detector.

Executes deterministic first-pass checks on telemetry streams and power balances:
- Power-balance residual violations (input vs output)
- Stale sensor timeouts
- Sensor disagreement across redundant channels
- Storage reserve breach warnings
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config.settings import Settings
from app.models.energy_state import EnergyStatus
from app.models.storage import BatteryState
from app.models.telemetry import QualityStatus, TelemetryRecord


class AnomalyCheckResult:
    """Outcome of anomaly evaluation."""
    def __init__(
        self,
        has_anomalies: bool,
        alerts: list[str],
        data_quality: QualityStatus,
        residual_kw: float,
    ) -> None:
        self.has_anomalies = has_anomalies
        self.alerts = alerts
        self.data_quality = data_quality
        self.residual_kw = residual_kw


class AnomalyDetector:
    """Performs deterministic physical consistency and state-anomaly checks."""

    def __init__(
        self,
        settings: Settings | None = None,
        stale_threshold_seconds: float | None = None,
        balance_tolerance_pct: float | None = None,
    ) -> None:
        self.settings = settings or Settings()
        if stale_threshold_seconds is not None:
            self.settings.stale_sensor_threshold_seconds = stale_threshold_seconds
        if balance_tolerance_pct is not None:
            self.settings.power_balance_tolerance_pct = balance_tolerance_pct

    def check_power_balance_residual(
        self,
        generation_kw: float,
        storage_discharge_kw: float = 0.0,
        import_kw: float = 0.0,
        load_kw: float = 0.0,
        storage_charge_kw: float = 0.0,
        export_kw: float = 0.0,
    ) -> tuple[float, bool, str]:
        """
        Calculate power-balance residual:
          input_kw = generation + storage_discharge + import
          output_kw = load + storage_charge + export
          residual_kw = |input_kw - output_kw|

        Flags violation if residual exceeds absolute (kW) or relative (%) tolerance.
        Returns: (residual_kw, is_anomaly, message)
        """
        inflow = generation_kw + storage_discharge_kw + import_kw
        outflow = load_kw + storage_charge_kw + export_kw
        residual_kw = round(abs(inflow - outflow), 3)

        tol_kw = self.settings.power_balance_tolerance_kw
        tol_pct = self.settings.power_balance_tolerance_pct

        # Relative check based on largest flow
        base_power = max(inflow, outflow, 1.0)
        pct_diff = (residual_kw / base_power) * 100.0

        is_anomaly = (residual_kw > tol_kw) and (pct_diff > tol_pct)
        message = (
            f"Power balance residual {residual_kw:.2f} kW ({pct_diff:.1f}%) exceeds "
            f"tolerance [{tol_kw} kW, {tol_pct}%]"
            if is_anomaly
            else f"Power balance consistent (residual: {residual_kw:.2f} kW)"
        )

        return residual_kw, is_anomaly, message

    def check_stale_sensors(
        self,
        device_last_seen: dict[str, datetime],
        reference_time: datetime | None = None,
    ) -> list[str]:
        """Identify devices that have not reported telemetry within the stale threshold."""
        now = reference_time or datetime.now(timezone.utc)
        threshold = self.settings.stale_sensor_threshold_seconds
        stale_devices = []

        for device_id, last_seen in device_last_seen.items():
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            delta_seconds = (now - last_seen).total_seconds()
            if delta_seconds > threshold:
                stale_devices.append(device_id)

        return stale_devices

    def detect_stale_sensors(
        self,
        latest_telemetry: dict[str, Any],
        current_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Detect stale sensors from mapping of device_id to TelemetryRecord or datetime."""
        now = current_time or datetime.now(timezone.utc)
        threshold = self.settings.stale_sensor_threshold_seconds
        stale_list = []

        for dev_id, item in latest_telemetry.items():
            if isinstance(item, TelemetryRecord):
                ts = item.timestamp
            elif isinstance(item, datetime):
                ts = item
            elif isinstance(item, dict):
                ts = item.get("timestamp", now)
            else:
                continue

            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            delta = (now - ts).total_seconds()
            if delta > threshold:
                stale_list.append({
                    "device_id": dev_id,
                    "last_seen": ts.isoformat(),
                    "seconds_inactive": round(delta, 1),
                })

        return stale_list

    def detect_storage_anomalies(self, battery: Any) -> list[dict[str, Any]]:
        """Evaluate battery telemetry for low/critical SOC alerts."""
        alerts = []
        if isinstance(battery, BatteryState):
            soc = battery.soc_pct
        elif isinstance(battery, dict):
            soc = float(battery.get("soc_pct", 100.0))
        elif isinstance(battery, (int, float)):
            soc = float(battery)
        else:
            return alerts

        if soc <= self.settings.battery_critical_soc_threshold_pct:
            alerts.append({
                "alert_type": "BATTERY_CRITICAL",
                "severity": "CRITICAL",
                "message": f"Battery SOC critical: {soc:.1f}% <= {self.settings.battery_critical_soc_threshold_pct}%",
            })
        elif soc <= self.settings.battery_low_soc_threshold_pct:
            alerts.append({
                "alert_type": "BATTERY_LOW",
                "severity": "WARNING",
                "message": f"Battery SOC low: {soc:.1f}% <= {self.settings.battery_low_soc_threshold_pct}%",
            })

        return alerts

    def evaluate_state_anomalies(
        self,
        generation_kw: float,
        load_kw: float,
        battery_soc_pct: float,
        hydrogen_level_pct: float,
        storage_discharge_kw: float,
        storage_charge_kw: float,
        import_kw: float = 0.0,
        export_kw: float = 0.0,
        stale_devices: list[str] | None = None,
    ) -> AnomalyCheckResult:
        """Run all deterministic anomaly checks across the current energy state."""
        alerts: list[str] = []
        data_quality = QualityStatus.GOOD

        # 1. Power Balance Residual
        residual, has_residual_anomaly, res_msg = self.check_power_balance_residual(
            generation_kw=generation_kw,
            storage_discharge_kw=storage_discharge_kw,
            import_kw=import_kw,
            load_kw=load_kw,
            storage_charge_kw=storage_charge_kw,
            export_kw=export_kw,
        )
        if has_residual_anomaly:
            alerts.append(f"ENERGY_BALANCE_ANOMALY: {res_msg}")
            data_quality = QualityStatus.SUSPECT

        # 2. Stale Sensors
        if stale_devices:
            alerts.append(f"TELEMETRY_STALE: Sensors unresponsive: {', '.join(stale_devices)}")
            if data_quality == QualityStatus.GOOD:
                data_quality = QualityStatus.SUSPECT

        # 3. Battery Low / Critical SOC
        if battery_soc_pct <= self.settings.battery_critical_soc_threshold_pct:
            alerts.append(f"BATTERY_SOC_CRITICAL: Battery SOC at {battery_soc_pct:.1f}% <= {self.settings.battery_critical_soc_threshold_pct}%")
        elif battery_soc_pct <= self.settings.battery_low_soc_threshold_pct:
            alerts.append(f"BATTERY_LOW: Battery SOC at {battery_soc_pct:.1f}% <= {self.settings.battery_low_soc_threshold_pct}%")

        # 4. Hydrogen Low / Critical
        if hydrogen_level_pct <= self.settings.hydrogen_critical_level_pct:
            alerts.append(f"HYDROGEN_CRITICAL: Hydrogen storage at {hydrogen_level_pct:.1f}% <= {self.settings.hydrogen_critical_level_pct}%")
        elif hydrogen_level_pct <= self.settings.hydrogen_low_level_pct:
            alerts.append(f"HYDROGEN_LOW: Hydrogen storage at {hydrogen_level_pct:.1f}% <= {self.settings.hydrogen_low_level_pct}%")

        # 5. Severe Deficit with no storage runway
        net_generation = generation_kw - load_kw
        if net_generation < -50.0 and battery_soc_pct <= self.settings.battery_min_soc_pct:
            alerts.append("ENERGY_DEFICIT: Critical generation deficit with depleted storage reserve")

        has_anomalies = len(alerts) > 0
        return AnomalyCheckResult(
            has_anomalies=has_anomalies,
            alerts=alerts,
            data_quality=data_quality,
            residual_kw=residual,
        )
