"""
HAL Device Registry and Dispatch Manager.
"""

from __future__ import annotations

from typing import Dict, Optional, List
import structlog

from app.hal.base import BaseHALAdapter
from app.hal.modbus_adapter import ModbusAdapter
from app.hal.opcua_adapter import OPCUAAdapter
from app.hal.can_adapter import CANAdapter
from app.hal.mqtt_adapter import MQTTAdapter
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class HALDeviceManager:
    """Manages all active HAL protocol adapters for station hardware devices."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._adapters: Dict[str, BaseHALAdapter] = {}

    def register_adapter(self, device_id: str, adapter: BaseHALAdapter) -> None:
        """Register a HAL protocol adapter instance."""
        self._adapters[device_id] = adapter
        logger.info("HAL Adapter registered", device_id=device_id, endpoint=adapter.endpoint)

    def get_adapter(self, device_id: str) -> Optional[BaseHALAdapter]:
        """Retrieve registered HAL adapter by device_id."""
        return self._adapters.get(device_id)

    def list_devices(self) -> List[str]:
        """List all registered device IDs."""
        return list(self._adapters.keys())
