"""
Frost OS Module 03 — Energy Engine.

Central engine executing the 13-step telemetry aggregation, power balance,
storage state estimation, anomaly evaluation, and EnergyState snapshot generation.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

from app.config.settings import Settings
from app.core.anomaly_detector import AnomalyDetector
from app.core.load_analyzer import LoadAnalyzer
from app.core.power_calculator import PowerCalculator
from app.core.storage_calculator import StorageCalculator
from app.core.telemetry_processor import TelemetryProcessor
from app.events.event_types import EnergyEventType
from app.models.energy_state import (
    EnergyState,
    EnergyStatus,
    GenerationBreakdown,
    LoadBreakdown,
)
from app.models.storage import BatteryState, HydrogenState, ThermalStorageState
from app.models.telemetry import (
    DeviceType,
    MetricType,
    QualityStatus,
    TelemetryRecord,
)

logger = structlog.get_logger(__name__)


class EnergyEngine:
    """Core domain service managing real-time station energy telemetry and state snapshots."""

    def __init__(self, settings: Settings, publisher: Any = None) -> None:
        self.settings = settings
        self.publisher = publisher
        self.processor = TelemetryProcessor(settings)
        self.power_calc = PowerCalculator()
        self.storage_calc = StorageCalculator(settings)
        self.load_analyzer = LoadAnalyzer()
        self.anomaly_detector = AnomalyDetector(settings)

        # Device telemetry caches
        self._devices_last_seen: dict[str, datetime] = {}
        self._generation_devices: dict[str, tuple[float, DeviceType]] = {}  # device_id -> (kw, type)
        self._load_devices: dict[str, tuple[float, str]] = {}              # device_id -> (kw, category)
        self._storage_telemetry: dict[str, float] = {
            "battery_soc_pct": 72.0,
            "battery_soh_pct": 98.0,
            "battery_temp_c": 15.0,
            "battery_power_kw": 0.0,
            "hydrogen_level_pct": 81.0,
            "hydrogen_fc_kw": 0.0,
            "hydrogen_ely_kw": 0.0,
            "thermal_kwh": 500.0,
            "thermal_temp_c": 65.0,
        }

        # EnergyState state tracking
        self._previous_state: EnergyState | None = None
        self._current_state: EnergyState = self._initialize_default_state()
        self._subscribers: list[asyncio.Queue] = []

    def _initialize_default_state(self) -> EnergyState:
        """Create baseline polar station state (120 kW solar, 180 kW wind, 340 kW load)."""
        now = datetime.now(timezone.utc)
        gen = GenerationBreakdown(solar=120.0, wind=180.0, other=0.0, total=300.0)
        load = LoadBreakdown(critical=120.0, operational=100.0, flexible=90.0, deferrable=30.0, total=340.0)
        net_kw = 300.0 - 340.0  # -40.0 kW (deficit)

        bess = self.storage_calc.calculate_battery_state(
            soc_pct=72.0,
            soh_pct=98.0,
            current_power_kw=0.0,
            deficit_kw=40.0,
        )
        h2 = self.storage_calc.calculate_hydrogen_state(level_pct=81.0)
        thermal = ThermalStorageState(stored_kwh=500.0, temperature_c=65.0)

        total_avail_stored = bess.available_energy_kwh + h2.usable_energy_kwh

        return EnergyState(
            timestamp=now,
            station_id=self.settings.station_id,
            generation_kw=gen,
            load_kw=340.0,
            load_breakdown=load,
            net_power_kw=net_kw,
            battery=bess,
            hydrogen=h2,
            thermal=thermal,
            available_power_kw=300.0,
            available_energy_kwh=total_avail_stored,
            available_dispatchable_power_kw=bess.discharge_limit_kw + h2.max_discharge_kw,
            available_stored_energy_kwh=total_avail_stored,
            estimated_time_to_min_soc_hours=bess.estimated_runway_hours,
            data_quality=QualityStatus.GOOD,
            status=EnergyStatus.DEFICIT,
            active_alerts=[],
            metadata={"source": "initialized_baseline"},
        )

    def get_current_state(self) -> EnergyState:
        """Retrieve current immutable EnergyState snapshot."""
        return self._current_state

    def register_websocket_queue(self, queue: asyncio.Queue) -> None:
        """Register a subscriber queue for live WebSocket state broadcasts."""
        self._subscribers.append(queue)

    def unregister_websocket_queue(self, queue: asyncio.Queue) -> None:
        """Unregister a subscriber queue."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def ingest_telemetry(self, raw_record: TelemetryRecord) -> tuple[EnergyState, list[EnergyEventType]]:
        """
        Ingest and process a single sensor reading through the 13-step pipeline.
        Returns the updated EnergyState and any detected event triggers.
        """
        # 1. Validation & Normalization
        record = self.processor.process(raw_record)
        self._devices_last_seen[record.device_id] = record.timestamp

        # 2. Update Device Cache based on device type & metric
        if record.device_type in (DeviceType.SOLAR, DeviceType.WIND, DeviceType.GENERATOR):
            if record.metric == MetricType.POWER_KW:
                self._generation_devices[record.device_id] = (record.value, record.device_type)

        elif record.device_type == DeviceType.LOAD:
            if record.metric == MetricType.POWER_KW:
                category = (
                    record.metadata.get("priority")
                    or record.metadata.get("tier")
                    or record.metadata.get("category")
                    or "OPERATIONAL"
                )
                self._load_devices[record.device_id] = (record.value, category)

        elif record.device_type == DeviceType.BATTERY:
            if record.metric == MetricType.STATE_OF_CHARGE_PCT:
                self._storage_telemetry["battery_soc_pct"] = record.value
            elif record.metric == MetricType.STATE_OF_HEALTH_PCT:
                self._storage_telemetry["battery_soh_pct"] = record.value
            elif record.metric == MetricType.POWER_KW:
                self._storage_telemetry["battery_power_kw"] = record.value
            elif record.metric == MetricType.TEMPERATURE_C:
                self._storage_telemetry["battery_temp_c"] = record.value

        elif record.device_type == DeviceType.HYDROGEN:
            if record.metric == MetricType.HYDROGEN_LEVEL_PCT:
                self._storage_telemetry["hydrogen_level_pct"] = record.value
            elif record.metric == MetricType.POWER_KW:
                is_electrolyzer = "electrolyzer" in record.device_id.lower()
                if is_electrolyzer:
                    self._storage_telemetry["hydrogen_ely_kw"] = record.value
                else:
                    self._storage_telemetry["hydrogen_fc_kw"] = record.value

        # 3. Aggregate Generation
        solar_total = sum(kw for kw, dt in self._generation_devices.values() if dt == DeviceType.SOLAR)
        wind_total = sum(kw for kw, dt in self._generation_devices.values() if dt == DeviceType.WIND)
        other_total = sum(kw for kw, dt in self._generation_devices.values() if dt not in (DeviceType.SOLAR, DeviceType.WIND))
        total_gen = solar_total + wind_total + other_total
        gen_breakdown = GenerationBreakdown(
            solar=round(solar_total, 2),
            wind=round(wind_total, 2),
            other=round(other_total, 2),
            total=round(total_gen, 2),
        )

        # 4. Aggregate Loads
        load_breakdown = self.load_analyzer.categorize_loads(self._load_devices)
        total_load = load_breakdown.total

        # 5. Storage Calculations
        bess_power = self._storage_telemetry["battery_power_kw"]
        bess_discharge = max(0.0, bess_power)
        bess_charge = max(0.0, -bess_power)

        net_power = round(total_gen - total_load, 3)

        deficit_for_battery = max(0.0, total_load - total_gen)
        bess_state = self.storage_calc.calculate_battery_state(
            soc_pct=self._storage_telemetry["battery_soc_pct"],
            soh_pct=self._storage_telemetry["battery_soh_pct"],
            current_power_kw=bess_power,
            temperature_c=self._storage_telemetry["battery_temp_c"],
            deficit_kw=deficit_for_battery,
        )

        h2_state = self.storage_calc.calculate_hydrogen_state(
            level_pct=self._storage_telemetry["hydrogen_level_pct"],
            fuel_cell_power_kw=self._storage_telemetry["hydrogen_fc_kw"],
            electrolyzer_power_kw=self._storage_telemetry["hydrogen_ely_kw"],
        )

        thermal_state = ThermalStorageState(
            stored_kwh=self._storage_telemetry["thermal_kwh"],
            temperature_c=self._storage_telemetry["thermal_temp_c"],
        )

        # 6. Check Anomalies & Stale Sensors
        stale_devices = self.anomaly_detector.check_stale_sensors(
            self._devices_last_seen,
            reference_time=record.timestamp,
        )
        anomaly_res = self.anomaly_detector.evaluate_state_anomalies(
            generation_kw=total_gen,
            load_kw=total_load,
            battery_soc_pct=bess_state.soc_pct,
            hydrogen_level_pct=h2_state.level_pct,
            storage_discharge_kw=bess_discharge,
            storage_charge_kw=bess_charge,
            stale_devices=stale_devices,
        )

        # 7. Energy Availability
        usable_storage_kwh = bess_state.available_energy_kwh + h2_state.usable_energy_kwh
        dispatchable_kw = bess_state.discharge_limit_kw + h2_state.max_discharge_kw

        # Determine overall operational status
        status = self.power_calc.determine_energy_status(net_power)
        if bess_state.soc_pct <= self.settings.battery_critical_soc_threshold_pct and status == EnergyStatus.DEFICIT:
            status = EnergyStatus.CRITICAL

        # 8. Construct Immutable EnergyState Snapshot
        new_state = EnergyState(
            timestamp=record.timestamp,
            station_id=self.settings.station_id,
            generation_kw=gen_breakdown,
            load_kw=total_load,
            load_breakdown=load_breakdown,
            net_power_kw=net_power,
            battery=bess_state,
            hydrogen=h2_state,
            thermal=thermal_state,
            available_power_kw=total_gen,
            available_energy_kwh=usable_storage_kwh,
            available_dispatchable_power_kw=dispatchable_kw,
            available_stored_energy_kwh=usable_storage_kwh,
            estimated_time_to_min_soc_hours=bess_state.estimated_runway_hours,
            data_quality=anomaly_res.data_quality,
            status=status,
            active_alerts=anomaly_res.alerts,
            metadata={"trigger_device": record.device_id, "trigger_metric": record.metric.value},
        )

        # 9. Detect Threshold Events for Redis Publishing
        detected_events = self._detect_events(self._current_state, new_state, anomaly_res)

        # Update cache
        self._previous_state = self._current_state
        self._current_state = new_state

        # 10. Broadcast to Active WebSocket Subscribers
        state_dict = new_state.model_dump(mode="json")
        for q in list(self._subscribers):
            try:
                q.put_nowait(state_dict)
            except Exception:
                pass

        return new_state, detected_events

    def process_telemetry_sync(
        self,
        records: list[TelemetryRecord],
    ) -> tuple[EnergyState, list[dict[str, Any]]]:
        """Synchronously process a batch of telemetry records."""
        last_state = self._current_state
        all_events: list[EnergyEventType] = []
        for r in records:
            last_state, evs = self.ingest_telemetry(r)
            all_events.extend(evs)

        formatted_alerts = [
            {
                "alert_type": getattr(ev, "value", str(ev)),
                "station_id": last_state.station_id,
            }
            for ev in all_events
            if getattr(ev, "value", str(ev)) != "ENERGY_STATE_UPDATED"
        ]
        return last_state, formatted_alerts

    async def process_telemetry(
        self,
        records: list[TelemetryRecord],
    ) -> tuple[EnergyState, list[dict[str, Any]]]:
        """Asynchronously process a batch of telemetry records, publishing events."""
        state, alerts = self.process_telemetry_sync(records)
        if self.publisher is not None:
            try:
                await self.publisher.publish_state_update(state)
                for a in alerts:
                    await self.publisher.publish_alert(
                        alert_type=a["alert_type"],
                        station_id=state.station_id,
                        payload={"alerts": state.active_alerts, "net_power_kw": state.net_power_kw},
                    )
            except Exception as ex:
                await logger.awarning("Publisher error in engine", error=str(ex))
        return state, alerts

    def get_latest_state(self, station_id: str | None = None) -> EnergyState | None:
        """Get the latest cached EnergyState."""
        return self._current_state

    def _detect_events(
        self,
        prev: EnergyState,
        curr: EnergyState,
        anomalies: Any,
    ) -> list[EnergyEventType]:
        """Detect operational threshold events triggered by state delta."""
        events: list[EnergyEventType] = [EnergyEventType.ENERGY_STATE_UPDATED]

        # Generation Drop Alert
        if prev and prev.generation.total > 10.0:
            drop_kw = prev.generation.total - curr.generation.total
            drop_pct = (drop_kw / prev.generation.total) * 100.0
            if drop_pct >= self.settings.generation_drop_alert_pct:
                events.append(EnergyEventType.GENERATION_DROP)

        # Load Spike Alert
        if prev and prev.load.total > 10.0:
            spike_kw = curr.load.total - prev.load.total
            spike_pct = (spike_kw / prev.load.total) * 100.0
            if spike_pct >= self.settings.load_spike_alert_pct:
                events.append(EnergyEventType.LOAD_SPIKE)

        # Battery Thresholds
        if curr.battery.soc_pct <= self.settings.battery_critical_soc_threshold_pct:
            if not prev or prev.battery.soc_pct > self.settings.battery_critical_soc_threshold_pct:
                events.append(EnergyEventType.STORAGE_CRITICAL)
        elif curr.battery.soc_pct <= self.settings.battery_low_soc_threshold_pct:
            if not prev or prev.battery.soc_pct > self.settings.battery_low_soc_threshold_pct:
                events.append(EnergyEventType.BATTERY_LOW)

        # Deficit / Surplus State Change
        if curr.status == EnergyStatus.DEFICIT and (not prev or prev.status != EnergyStatus.DEFICIT):
            events.append(EnergyEventType.DEFICIT_DETECTED)
        elif curr.status == EnergyStatus.SURPLUS and (not prev or prev.status != EnergyStatus.SURPLUS):
            events.append(EnergyEventType.SURPLUS_DETECTED)

        # Telemetry anomaly
        if anomalies.has_anomalies:
            events.append(EnergyEventType.TELEMETRY_ANOMALY)

        return events

    def analyze_generation_event(
        self,
        station_id: str,
        event_or_prev: Any,
        current_gen_kw: float | None = None,
    ) -> dict[str, Any]:
        """Provide event analysis for Module 01 Orchestrator."""
        if isinstance(event_or_prev, dict):
            payload = event_or_prev.get("payload", event_or_prev)
            previous_gen_kw = float(payload.get("previous_generation_kw", 180.0))
            current_gen_kw = float(payload.get("current_generation_kw", 70.0))
        else:
            previous_gen_kw = float(event_or_prev)
            current_gen_kw = float(current_gen_kw or 0.0)

        drop_kw = max(0.0, previous_gen_kw - current_gen_kw)
        drop_pct = (drop_kw / previous_gen_kw) * 100.0 if previous_gen_kw > 0 else 0.0

        current_load = self._current_state.load.total if self._current_state else 340.0
        net_after_drop = current_gen_kw - current_load
        deficit_kw = max(0.0, -net_after_drop)

        battery_available = self._current_state.battery.available_energy_kwh if self._current_state else 312.0
        runway = (battery_available / deficit_kw) if deficit_kw > 0 else 999.0

        return {
            "station_id": station_id,
            "event_type": "GENERATION_DROP",
            "previous_generation_kw": round(previous_gen_kw, 2),
            "current_generation_kw": round(current_gen_kw, 2),
            "drop_kw": round(drop_kw, 2),
            "drop_pct": round(drop_pct, 1),
            "cause_assessment": (
                f"Generation declined by {drop_kw:.1f} kW ({drop_pct:.1f}%). "
                f"Net station deficit is now {deficit_kw:.1f} kW."
            ),
            "battery_runway_hours": round(runway, 1) if runway < 999.0 else 0.0,
            "immediate_risk": runway < 2.0,
            "requires_load_adjustment": deficit_kw > 0.0,
        }
