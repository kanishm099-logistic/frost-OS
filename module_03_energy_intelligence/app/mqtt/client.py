"""
Frost OS Module 03 — MQTT Telemetry Ingestion Client.

Subscribes to polar telemetry topics, parses incoming messages, and delivers
normalized TelemetryRecord models to the EnergyEngine. Supports resilient reconnection
and an in-memory test fallback mode.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from typing import Any, Callable, Coroutine
import uuid

import structlog

from app.config.settings import Settings
from app.models.telemetry import (
    DeviceType,
    MetricType,
    QualityStatus,
    TelemetryRecord,
)
from app.mqtt.topics import ParsedTopic, parse_telemetry_topic

logger = structlog.get_logger(__name__)


class MQTTTelemetryClient:
    """
    MQTT client for ingesting polar microgrid telemetry.
    Supports asynchronous message handling and decoupled queue processing.
    """

    def __init__(
        self,
        settings: Settings,
        on_telemetry_callback: Callable[[list[TelemetryRecord]], Coroutine[Any, Any, None]] | None = None,
    ):
        self.settings = settings
        self.callback = on_telemetry_callback
        self.running = False
        self._client = None
        self._loop_task: asyncio.Task | None = None
        self._message_queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        self._mock_mode = False

    async def start(self) -> None:
        """Start the MQTT client and processing loop."""
        self.running = True
        self._loop_task = asyncio.create_task(self._process_queue())

        try:
            import paho.mqtt.client as mqtt

            # Create Paho MQTT Client (supports both v1 and v2 API)
            try:
                self._client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=self.settings.mqtt_client_id,
                )
            except (AttributeError, TypeError):
                self._client = mqtt.Client(client_id=self.settings.mqtt_client_id)

            if self.settings.mqtt_username:
                self._client.username_pw_set(
                    self.settings.mqtt_username,
                    self.settings.mqtt_password,
                )

            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message

            # Connect non-blocking using loop in thread
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._connect_sync,
            )
            await logger.ainfo(
                "MQTT client connected",
                host=self.settings.mqtt_broker_host,
                port=self.settings.mqtt_broker_port,
            )
        except Exception as exc:
            self._mock_mode = True
            await logger.awarning(
                "MQTT broker unavailable; continuing in internal/mock ingestion mode",
                error=str(exc),
            )

    def _connect_sync(self) -> None:
        """Synchronous connect and start loop in background thread."""
        if self._client:
            self._client.connect(
                self.settings.mqtt_broker_host,
                self.settings.mqtt_broker_port,
                keepalive=60,
            )
            self._client.loop_start()

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: Any, *args: Any) -> None:
        """Callback on broker connection."""
        topic_filter = f"{self.settings.mqtt_topic_prefix}/#"
        client.subscribe(topic_filter, qos=self.settings.mqtt_qos)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Callback on incoming MQTT message; queues to async consumer."""
        try:
            self._message_queue.put_nowait((msg.topic, msg.payload))
        except Exception:
            pass

    async def ingest_payload(self, topic: str, payload_bytes: bytes) -> None:
        """Direct injection for testing or simulation."""
        await self._message_queue.put((topic, payload_bytes))

    async def _process_queue(self) -> None:
        """Async worker consuming incoming messages from the queue."""
        while self.running:
            try:
                topic, payload = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                records = self._parse_message(topic, payload)
                if records and self.callback:
                    await self.callback(records)
                self._message_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as exc:
                await logger.aerror("Failed to process MQTT message", error=str(exc))

    def _parse_message(self, topic: str, payload: bytes) -> list[TelemetryRecord]:
        """Convert topic and raw bytes into validated TelemetryRecord instances."""
        parsed = parse_telemetry_topic(topic)
        if not parsed:
            return []

        try:
            data = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            try:
                data = float(payload.decode("utf-8").strip())
            except Exception:
                return []

        if isinstance(data, (int, float)):
            data = {"value": float(data)}

        records: list[TelemetryRecord] = []
        now = datetime.now(timezone.utc)

        if isinstance(data, dict):
            # If the payload is a full TelemetryRecord format
            if "metric" in data and "value" in data:
                try:
                    rec = TelemetryRecord.model_validate(data)
                    return [rec]
                except Exception:
                    pass

            # If payload has individual metrics: {"power_kw": 120.5, "voltage_v": 400.0}
            for key, val in data.items():
                if isinstance(val, (int, float)):
                    try:
                        metric = MetricType(key.upper())
                    except ValueError:
                        continue

                    # Unit guessing based on metric
                    unit = self._default_unit_for_metric(metric)
                    records.append(
                        TelemetryRecord(
                            record_id=str(uuid.uuid4()),
                            timestamp=now,
                            station_id=parsed.station_id,
                            device_id=parsed.device_id,
                            device_type=parsed.device_type,
                            metric=metric,
                            value=float(val),
                            unit=unit,
                            quality=QualityStatus.GOOD,
                            source="mqtt",
                        )
                    )
            # If topic had specific metric and payload has single value
            if not records and parsed.metric and "value" in data:
                val = float(data["value"])
                unit = data.get("unit", self._default_unit_for_metric(parsed.metric))
                records.append(
                    TelemetryRecord(
                        record_id=str(uuid.uuid4()),
                        timestamp=now,
                        station_id=parsed.station_id,
                        device_id=parsed.device_id,
                        device_type=parsed.device_type,
                        metric=parsed.metric,
                        value=val,
                        unit=unit,
                        quality=QualityStatus.GOOD,
                        source="mqtt",
                    )
                )

        return records

    @staticmethod
    def _default_unit_for_metric(metric: MetricType) -> str:
        """Map metric type to canonical unit."""
        mapping = {
            MetricType.POWER_KW: "kW",
            MetricType.VOLTAGE_V: "V",
            MetricType.CURRENT_A: "A",
            MetricType.FREQUENCY_HZ: "Hz",
            MetricType.SOC_PCT: "%",
            MetricType.SOH_PCT: "%",
            MetricType.TEMPERATURE_C: "°C",
            MetricType.PRESSURE_BAR: "bar",
            MetricType.FLOW_RATE_KG_H: "kg/h",
            MetricType.ENERGY_KWH: "kWh",
            MetricType.IRRADIANCE_W_M2: "W/m²",
            MetricType.WIND_SPEED_M_S: "m/s",
        }
        return mapping.get(metric, "unit")

    async def stop(self) -> None:
        """Stop MQTT client and processing loop."""
        self.running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

        if self._client:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._disconnect_sync)
            except Exception:
                pass

    def _disconnect_sync(self) -> None:
        """Synchronously stop client loop and disconnect."""
        if self._client:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
