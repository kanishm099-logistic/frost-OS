"""
Modbus TCP/RTU Protocol Adapter.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Tuple
import structlog

from app.hal.base import BaseHALAdapter
from app.models.command import ProtocolCommandModel, CommandAttemptModel

logger = structlog.get_logger(__name__)


class ModbusAdapter(BaseHALAdapter):
    """HAL Adapter for Modbus TCP/RTU protocol communications."""

    async def connect(self) -> bool:
        self.is_connected = True
        logger.info("ModbusAdapter connected", device_id=self.device_id, endpoint=self.endpoint)
        return True

    async def disconnect(self) -> None:
        self.is_connected = False
        logger.info("ModbusAdapter disconnected", device_id=self.device_id)

    async def get_state(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "protocol": "MODBUS_TCP",
            "online": self.is_connected,
            "power_kw": self.capabilities.get("current_power_kw", 0.0),
            "status": "OPERATIONAL",
        }

    def validate_command(self, command: ProtocolCommandModel) -> Tuple[bool, str]:
        max_power = float(self.capabilities.get("max_power_kw", 250.0))
        req_power = float(command.parameters.get("power_kw", command.parameters.get("discharge_rate_kw", 0.0)))
        if req_power > max_power:
            return False, f"Modbus command parameter {req_power} kW exceeds device maximum capacity {max_power} kW"
        return True, ""

    async def execute_command(self, command: ProtocolCommandModel) -> CommandAttemptModel:
        attempt_id = f"ATT-{uuid.uuid4().hex[:8].upper()}"
        valid, msg = self.validate_command(command)
        if not valid:
            return CommandAttemptModel(
                attempt_id=attempt_id,
                command_id=command.command_id,
                device_id=self.device_id,
                protocol="MODBUS_TCP",
                status="REJECTED",
                error_message=msg,
            )

        # Update local simulated state
        req_power = float(command.parameters.get("power_kw", command.parameters.get("discharge_rate_kw", 0.0)))
        self.capabilities["current_power_kw"] = req_power

        logger.info("Modbus command executed successfully", device_id=self.device_id, command=command.command_name)
        return CommandAttemptModel(
            attempt_id=attempt_id,
            command_id=command.command_id,
            device_id=self.device_id,
            protocol="MODBUS_TCP",
            status="ACKNOWLEDGED",
            response_payload={"modbus_register_write": "SUCCESS", "written_kw": req_power},
        )

    async def stop(self) -> bool:
        self.capabilities["current_power_kw"] = 0.0
        return True

    async def health_check(self) -> bool:
        return self.is_connected
