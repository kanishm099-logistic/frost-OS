"""
Execution State Machine Manager.

Tracks state transitions:
RECEIVED -> AUTH_CHECK -> SAFETY_CHECK -> VALIDATING -> QUEUED -> EXECUTING -> OBSERVING -> VERIFYING -> COMPLETED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from pydantic import BaseModel, Field

from app.models.execution import ExecutionStateEnum
import structlog

logger = structlog.get_logger(__name__)


class ExecutionStateTransition(BaseModel):
    from_state: ExecutionStateEnum
    to_state: ExecutionStateEnum
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str


class ExecutionStateMachine:
    """Tracks state transitions for an execution run."""

    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.current_state = ExecutionStateEnum.RECEIVED
        self.transitions: List[ExecutionStateTransition] = []

    def transition_to(self, new_state: ExecutionStateEnum, reason: str) -> ExecutionStateTransition:
        t = ExecutionStateTransition(from_state=self.current_state, to_state=new_state, reason=reason)
        logger.info("Execution state transition", execution_id=self.execution_id, from_state=self.current_state.value, to_state=new_state.value, reason=reason)
        self.current_state = new_state
        self.transitions.append(t)
        return t
