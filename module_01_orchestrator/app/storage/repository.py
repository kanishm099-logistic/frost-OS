"""
Frost OS Module 01 — Repository Layer.

Provides async data-access repositories for events, decisions,
action plans, and audit logs. Uses SQLAlchemy async sessions
with transaction management.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.event import EventRecord, StationEvent
from app.models.decision import (
    DecisionRecord,
    DecisionStatus,
    DecisionTransitionRecord,
    Decision,
    DecisionContext,
    validate_transition,
)
from app.models.action_plan import (
    ActionPlanRecord,
    AuthorizationRecord,
    AuditLogRecord,
    WorkflowRunRecord,
    ActionPlan,
    Authorization,
    PlanStatus,
)

logger = structlog.get_logger(__name__)


class EventRepository:
    """Data access for station events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, event: StationEvent) -> EventRecord:
        """Persist a station event."""
        record = EventRecord.from_domain(event)
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_id(self, event_id: str) -> EventRecord | None:
        """Retrieve an event by its ID."""
        result = await self._session.execute(
            select(EventRecord).where(EventRecord.event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def exists(self, event_id: str) -> bool:
        """Check if an event already exists in the database."""
        record = await self.get_by_id(event_id)
        return record is not None

    async def get_by_station(
        self, station_id: str, limit: int = 50
    ) -> list[EventRecord]:
        """Retrieve recent events for a station."""
        result = await self._session.execute(
            select(EventRecord)
            .where(EventRecord.station_id == station_id)
            .order_by(EventRecord.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class DecisionRepository:
    """Data access for decisions and their state transitions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, decision: Decision) -> DecisionRecord:
        """Persist a new decision."""
        record = DecisionRecord(
            decision_id=decision.decision_id,
            event_id=decision.event_id,
            station_id=decision.station_id,
            correlation_id=decision.correlation_id,
            status=decision.status,
            workflow_name=decision.workflow_name,
            context_data=decision.context.model_dump(mode="json") if decision.context else None,
            action_plan_id=decision.action_plan_id,
            created_at=decision.created_at,
            updated_at=decision.updated_at,
        )
        self._session.add(record)
        await self._session.flush()

        # Record initial transition
        await self._record_transition(
            decision.decision_id,
            DecisionStatus.DETECTED,
            DecisionStatus.DETECTED,
            reason="Decision created",
            actor="system",
        )

        return record

    async def get_by_id(self, decision_id: str) -> DecisionRecord | None:
        """Retrieve a decision by its ID."""
        result = await self._session.execute(
            select(DecisionRecord).where(DecisionRecord.decision_id == decision_id)
        )
        return result.scalar_one_or_none()

    async def transition(
        self,
        decision_id: str,
        new_status: DecisionStatus,
        reason: str = "",
        actor: str = "system",
        context_data: dict | None = None,
        action_plan_id: str | None = None,
    ) -> DecisionRecord:
        """
        Transition a decision to a new state.

        Validates the transition against the state machine,
        persists the transition record, and updates the decision.
        """
        record = await self.get_by_id(decision_id)
        if record is None:
            raise ValueError(f"Decision {decision_id} not found")

        current_status = record.status
        if not validate_transition(current_status, new_status):
            raise ValueError(
                f"Invalid transition: {current_status.value} → {new_status.value} "
                f"for decision {decision_id}"
            )

        # Update decision
        update_values: dict[str, Any] = {
            "status": new_status,
            "updated_at": datetime.now(timezone.utc),
        }
        if context_data is not None:
            update_values["context_data"] = context_data
        if action_plan_id is not None:
            update_values["action_plan_id"] = action_plan_id

        await self._session.execute(
            update(DecisionRecord)
            .where(DecisionRecord.decision_id == decision_id)
            .values(**update_values)
        )

        # Record transition
        await self._record_transition(
            decision_id, current_status, new_status, reason, actor
        )

        # Refresh record
        await self._session.refresh(record)
        return record

    async def get_transitions(self, decision_id: str) -> list[DecisionTransitionRecord]:
        """Retrieve all transitions for a decision."""
        result = await self._session.execute(
            select(DecisionTransitionRecord)
            .where(DecisionTransitionRecord.decision_id == decision_id)
            .order_by(DecisionTransitionRecord.timestamp.asc())
        )
        return list(result.scalars().all())

    async def _record_transition(
        self,
        decision_id: str,
        from_status: DecisionStatus,
        to_status: DecisionStatus,
        reason: str,
        actor: str,
    ) -> None:
        """Record a state transition in the audit trail."""
        transition = DecisionTransitionRecord(
            id=str(uuid.uuid4()),
            decision_id=decision_id,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            actor=actor,
            timestamp=datetime.now(timezone.utc),
        )
        self._session.add(transition)
        await self._session.flush()


class ActionPlanRepository:
    """Data access for action plans and authorizations."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, plan: ActionPlan) -> ActionPlanRecord:
        """Persist a new action plan."""
        record = ActionPlanRecord(
            plan_id=plan.plan_id,
            trigger_event_id=plan.trigger_event_id,
            decision_id=plan.decision_id,
            station_id=plan.station_id,
            status=plan.status,
            reason=plan.reason,
            actions=[a.model_dump(mode="json") for a in plan.actions],
            projected_reserve_kwh=plan.projected_reserve_kwh,
            required_reserve_kwh=plan.required_reserve_kwh,
            safety_status=plan.safety_status,
            requires_authorization=plan.requires_authorization,
            is_emergency=plan.is_emergency,
            created_at=plan.created_at,
            expires_at=plan.expires_at,
            metadata_json=plan.metadata,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get_by_id(self, plan_id: str) -> ActionPlanRecord | None:
        """Retrieve an action plan by its ID."""
        result = await self._session.execute(
            select(ActionPlanRecord).where(ActionPlanRecord.plan_id == plan_id)
        )
        return result.scalar_one_or_none()

    async def update_status(self, plan_id: str, status: PlanStatus) -> ActionPlanRecord:
        """Update the status of an action plan."""
        await self._session.execute(
            update(ActionPlanRecord)
            .where(ActionPlanRecord.plan_id == plan_id)
            .values(status=status)
        )
        record = await self.get_by_id(plan_id)
        if record is None:
            raise ValueError(f"Action plan {plan_id} not found")
        return record

    async def save_authorization(self, auth: Authorization) -> AuthorizationRecord:
        """Persist an authorization decision."""
        record = AuthorizationRecord(
            authorization_id=auth.authorization_id,
            plan_id=auth.plan_id,
            decision=auth.decision,
            authorized_by=auth.authorized_by,
            reason=auth.reason,
            timestamp=auth.timestamp,
        )
        self._session.add(record)
        await self._session.flush()
        return record


class AuditRepository:
    """Append-only audit log repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        station_id: str,
        correlation_id: str,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        status: str = "success",
    ) -> None:
        """Append an entry to the audit log."""
        record = AuditLogRecord(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            station_id=station_id,
            correlation_id=correlation_id,
            actor=actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            status=status,
        )
        self._session.add(record)
        await self._session.flush()

        await logger.ainfo(
            "Audit log entry",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            station_id=station_id,
            correlation_id=correlation_id,
            status=status,
        )


class WorkflowRunRepository:
    """Data access for workflow run tracking."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        decision_id: str,
        workflow_name: str,
        station_id: str,
        correlation_id: str,
    ) -> WorkflowRunRecord:
        """Create a new workflow run record."""
        record = WorkflowRunRecord(
            workflow_run_id=str(uuid.uuid4()),
            decision_id=decision_id,
            workflow_name=workflow_name,
            station_id=station_id,
            correlation_id=correlation_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def complete(
        self,
        workflow_run_id: str,
        result_data: dict | None = None,
        error_message: str | None = None,
    ) -> None:
        """Mark a workflow run as completed or failed."""
        status = "completed" if error_message is None else "failed"
        await self._session.execute(
            update(WorkflowRunRecord)
            .where(WorkflowRunRecord.workflow_run_id == workflow_run_id)
            .values(
                status=status,
                completed_at=datetime.now(timezone.utc),
                result_data=result_data,
                error_message=error_message,
            )
        )

    async def get_by_id(self, workflow_run_id: str) -> WorkflowRunRecord | None:
        """Retrieve a workflow run by its ID."""
        result = await self._session.execute(
            select(WorkflowRunRecord).where(
                WorkflowRunRecord.workflow_run_id == workflow_run_id
            )
        )
        return result.scalar_one_or_none()

    async def get_by_decision(self, decision_id: str) -> list[WorkflowRunRecord]:
        """Retrieve all workflow runs for a decision."""
        result = await self._session.execute(
            select(WorkflowRunRecord)
            .where(WorkflowRunRecord.decision_id == decision_id)
            .order_by(WorkflowRunRecord.started_at.desc())
        )
        return list(result.scalars().all())
