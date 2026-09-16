"""
Command Manager & Resource Locking Engine.

Enforces:
1. Command Idempotency (deduplicates commands using idempotency_key).
2. Resource Locking (prevents conflicting concurrent actions e.g. CHARGE vs DISCHARGE on same battery).
3. Timeout handling and non-blocking wait.
"""

from __future__ import annotations

import uuid
import asyncio
from typing import Dict, Any, Tuple, Optional, Set
import structlog

from app.models.command import ProtocolCommandModel, CommandAttemptModel
from app.models.execution import ActionItemModel
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class CommandManager:
    """Manages command idempotency, resource locks, and execution timeouts."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._processed_idempotency_keys: Set[str] = set()
        self._active_resource_locks: Dict[str, str] = {}  # resource_id -> plan_id

    def check_idempotency(self, idempotency_key: str) -> bool:
        """
        Check if idempotency key has already been executed.
        Returns True if NEW (valid to execute), False if DUPLICATE (reject execution).
        """
        if idempotency_key in self._processed_idempotency_keys:
            logger.warning("Duplicate command blocked by idempotency key", idempotency_key=idempotency_key)
            return False
        return True

    def mark_idempotency_executed(self, idempotency_key: str) -> None:
        """Record idempotency key as executed."""
        self._processed_idempotency_keys.add(idempotency_key)

    def acquire_resource_lock(self, resource_id: str, plan_id: str) -> Tuple[bool, str]:
        """
        Acquire execution lock on target hardware resource.
        Prevents conflicting concurrent operations.
        """
        existing_owner = self._active_resource_locks.get(resource_id)
        if existing_owner and existing_owner != plan_id:
            return False, f"Resource '{resource_id}' is locked by concurrent plan '{existing_owner}'."

        self._active_resource_locks[resource_id] = plan_id
        logger.info("Resource lock acquired", resource_id=resource_id, plan_id=plan_id)
        return True, ""

    def release_resource_lock(self, resource_id: str, plan_id: str) -> None:
        """Release execution lock on target hardware resource."""
        if self._active_resource_locks.get(resource_id) == plan_id:
            del self._active_resource_locks[resource_id]
            logger.info("Resource lock released", resource_id=resource_id, plan_id=plan_id)

    def translate_action_to_command(self, action: ActionItemModel, idempotency_key: str) -> ProtocolCommandModel:
        """
        Translates high-level ActionItemModel into low-level ProtocolCommandModel.
        """
        command_id = f"CMD-{uuid.uuid4().hex[:8].upper()}"
        return ProtocolCommandModel(
            command_id=command_id,
            idempotency_key=idempotency_key,
            action_id=action.action_id,
            plan_id=action.plan_id,
            device_id=action.target_id,
            protocol="SIMULATED",
            endpoint="hal://simulated",
            command_name=action.action_type.value,
            parameters=action.parameters,
            timeout_seconds=action.timeout_seconds,
        )
