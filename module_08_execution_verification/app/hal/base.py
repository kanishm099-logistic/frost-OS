"""
Abstract Hardware Abstraction Layer (HAL) Base Adapter.

All protocol adapters (Modbus, OPC-UA, CAN, MQTT, Simulated) implement this common interface.
Business logic must NOT know vendor-specific registers or protocol internals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from app.models.command import ProtocolCommandModel, CommandAttemptModel


class BaseHALAdapter(ABC):
    """Common Hardware Abstraction Layer Adapter Interface."""

    def __init__(self, device_id: str, endpoint: str, capabilities: Dict[str, Any]):
        self.device_id = device_id
        self.endpoint = endpoint
        self.capabilities = capabilities
        self.is_connected = False

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to underlying hardware protocol endpoint."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from protocol endpoint."""
        pass

    @abstractmethod
    async def get_state(self) -> Dict[str, Any]:
        """Fetch live hardware telemetry and state."""
        pass

    @abstractmethod
    def validate_command(self, command: ProtocolCommandModel) -> Tuple[bool, str]:
        """Validate protocol command against local device capabilities."""
        pass

    @abstractmethod
    async def execute_command(self, command: ProtocolCommandModel) -> CommandAttemptModel:
        """Execute validated protocol command on physical hardware."""
        pass

    @abstractmethod
    async def stop(self) -> bool:
        """Emergency hardware stop / safe state transition."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Check hardware responsiveness and link quality."""
        pass
