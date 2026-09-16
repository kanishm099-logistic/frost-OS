"""
Frost OS Module 01 — Central Orchestrator.

The main coordination class that ties together:
event validation → classification → routing → workflow execution
→ decision management → action plan creation → authorization
→ execution → verification.

This is the heart of Module 01, but it delegates all domain
logic to specialized components (router, workflow engine,
decision manager, module clients).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog

from app.clients.diagnostic_client import DiagnosticClient
from app.clients.energy_client import EnergyClient
from app.clients.execution_client import ExecutionClient
from app.clients.forecast_client import ForecastClient
from app.clients.mission_client import MissionClient
from app.clients.optimizer_client import OptimizerClient
from app.clients.reserve_client import ReserveClient
from app.config.settings import Settings
from app.core.decision_manager import DecisionManager
from app.core.event_router import EventRouter
from app.core.workflow_engine import WorkflowEngine
from app.events.publisher import EventPublisher
from app.models.action_plan import (
    ActionPlan,
    Authorization,
    AuthorizationDecision,
    PlanStatus,
)
from app.models.decision import Decision, DecisionContext, DecisionStatus
from app.models.event import StationEvent
from app.storage.repository import (
    ActionPlanRepository,
    AuditRepository,
    DecisionRepository,
    EventRepository,
    WorkflowRunRepository,
)

logger = structlog.get_logger(__name__)


@dataclass
class ModuleClients:
    """Container for all module REST clients."""
    energy: EnergyClient
    forecast: ForecastClient
    diagnostic: DiagnosticClient
    mission: MissionClient
    optimizer: OptimizerClient
    reserve: ReserveClient
    execution: ExecutionClient


class Orchestrator:
    """
    Central orchestration engine for Frost OS Module 01.

    Coordinates the full event → action plan → execution pipeline.
    Delegates all domain logic to specialized components.
    """

    def __init__(
        self,
        settings: Settings,
        router: EventRouter,
        workflow_engine: WorkflowEngine,
        decision_manager: DecisionManager,
        clients: ModuleClients,
        publisher: EventPublisher | None = None,
        ws_manager: Any = None,
    ) -> None:
        self._settings = settings
        self._router = router
        self._workflow_engine = workflow_engine
        self._decision_manager = decision_manager
        self._clients = clients
        self._publisher = publisher
        self._ws_manager = ws_manager

    async def process_event(
        self,
        event: StationEvent,
        event_repo: EventRepository,
        decision_repo: DecisionRepository,
        plan_repo: ActionPlanRepository,
        audit_repo: AuditRepository,
        workflow_repo: WorkflowRunRepository,
    ) -> dict[str, Any]:
        """
        Process a station event through the full orchestration pipeline.

        Returns a summary dict with decision_id, plan_id, and status.
        """
        correlation_id = event.correlation_id

        await logger.ainfo(
            "Processing event",
            event_id=event.event_id,
            event_type=event.event_type.value,
            station_id=event.station_id,
            correlation_id=correlation_id,
        )

        # ── 1. Persist event ─────────────────────────────────────────
        await event_repo.save(event)
        await audit_repo.log(
            station_id=event.station_id,
            correlation_id=correlation_id,
            actor="orchestrator",
            action="event_received",
            resource_type="event",
            resource_id=event.event_id,
            details={"event_type": event.event_type.value, "severity": event.severity.value},
        )

        # ── 2. Classify & Route ──────────────────────────────────────
        route = self._router.classify(event)
        effective_severity = self._router.get_severity(event)
        event.severity = effective_severity

        await logger.ainfo(
            "Event classified",
            event_id=event.event_id,
            workflow=route.workflow_name,
            severity=effective_severity.value,
            affected_modules=list(route.affected_modules),
        )

        # Broadcast to WebSocket
        await self._broadcast_ws({
            "type": "event_classified",
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "workflow": route.workflow_name,
            "severity": effective_severity.value,
            "correlation_id": correlation_id,
        })

        # ── 3. Create Decision ───────────────────────────────────────
        decision = self._decision_manager.create_decision(event, route.workflow_name)
        await decision_repo.save(decision)

        # ── 4. Transition: DETECTED → ANALYZING ─────────────────────
        await decision_repo.transition(
            decision.decision_id,
            DecisionStatus.ANALYZING,
            reason=f"Starting workflow: {route.workflow_name}",
        )

        await self._broadcast_ws({
            "type": "decision_update",
            "decision_id": decision.decision_id,
            "status": DecisionStatus.ANALYZING.value,
            "correlation_id": correlation_id,
        })

        # ── 5. Execute Workflow ──────────────────────────────────────
        workflow_run = await workflow_repo.save(
            decision_id=decision.decision_id,
            workflow_name=route.workflow_name,
            station_id=event.station_id,
            correlation_id=correlation_id,
        )

        try:
            context = await self._workflow_engine.execute(
                workflow_name=route.workflow_name,
                event=event,
                context=decision.context,
                clients=self._clients,
            )

            await workflow_repo.complete(
                workflow_run.workflow_run_id,
                result_data={"degraded_modules": context.degraded_modules},
            )

        except Exception as exc:
            await logger.aerror(
                "Workflow execution failed",
                workflow=route.workflow_name,
                error=str(exc),
                correlation_id=correlation_id,
            )
            await workflow_repo.complete(
                workflow_run.workflow_run_id,
                error_message=str(exc),
            )
            await decision_repo.transition(
                decision.decision_id,
                DecisionStatus.EXECUTION_FAILED,
                reason=f"Workflow failed: {str(exc)}",
            )
            await audit_repo.log(
                station_id=event.station_id,
                correlation_id=correlation_id,
                actor="orchestrator",
                action="workflow_failed",
                resource_type="decision",
                resource_id=decision.decision_id,
                details={"error": str(exc)},
                status="error",
            )
            return {
                "decision_id": decision.decision_id,
                "status": DecisionStatus.EXECUTION_FAILED.value,
                "error": str(exc),
            }

        # ── 6. Transition: ANALYZING → PREDICTED → OPTIMIZING → VALIDATING
        await decision_repo.transition(
            decision.decision_id,
            DecisionStatus.PREDICTED,
            reason="Module analysis complete",
        )
        await decision_repo.transition(
            decision.decision_id,
            DecisionStatus.OPTIMIZING,
            reason="Optimization computed",
        )
        await decision_repo.transition(
            decision.decision_id,
            DecisionStatus.VALIDATING,
            reason="Safety/reserve validation complete",
            context_data=context.model_dump(mode="json"),
        )

        # ── 7. Build Action Plan ─────────────────────────────────────
        plan = self._decision_manager.build_action_plan(decision, context, event)
        await plan_repo.save(plan)

        await audit_repo.log(
            station_id=event.station_id,
            correlation_id=correlation_id,
            actor="orchestrator",
            action="action_plan_created",
            resource_type="action_plan",
            resource_id=plan.plan_id,
            details={
                "actions_count": len(plan.actions),
                "requires_authorization": plan.requires_authorization,
                "is_emergency": plan.is_emergency,
                "safety_status": plan.safety_status.value,
            },
        )

        # ── 8. Authorization / Emergency Bypass ──────────────────────
        if plan.is_emergency:
            # Emergency — bypass authorization, proceed to execution
            await decision_repo.transition(
                decision.decision_id,
                DecisionStatus.AUTHORIZED,
                reason="Emergency bypass — M07 flagged as emergency",
            )
            await plan_repo.update_status(plan.plan_id, PlanStatus.AUTHORIZED)

            await audit_repo.log(
                station_id=event.station_id,
                correlation_id=correlation_id,
                actor="system:emergency_bypass",
                action="emergency_authorization",
                resource_type="action_plan",
                resource_id=plan.plan_id,
                details={"reason": "M07 emergency flag"},
            )

            await self._broadcast_ws({
                "type": "emergency_bypass",
                "plan_id": plan.plan_id,
                "decision_id": decision.decision_id,
                "correlation_id": correlation_id,
            })

            # Execute immediately
            execution_result = await self._execute_plan(
                plan, decision, event_repo, decision_repo, plan_repo, audit_repo
            )

            return {
                "decision_id": decision.decision_id,
                "plan_id": plan.plan_id,
                "status": "emergency_executed",
                "execution": execution_result,
            }

        else:
            # Normal — await human authorization
            await decision_repo.transition(
                decision.decision_id,
                DecisionStatus.AWAITING_AUTHORIZATION,
                reason="Action plan requires human authorization",
                action_plan_id=plan.plan_id,
            )

            await self._broadcast_ws({
                "type": "awaiting_authorization",
                "plan_id": plan.plan_id,
                "decision_id": decision.decision_id,
                "reason": plan.reason,
                "actions_count": len(plan.actions),
                "correlation_id": correlation_id,
            })

            # Publish to Redis
            if self._publisher:
                await self._publisher.publish_action_plan(
                    plan.model_dump(mode="json")
                )

            return {
                "decision_id": decision.decision_id,
                "plan_id": plan.plan_id,
                "status": DecisionStatus.AWAITING_AUTHORIZATION.value,
                "requires_authorization": True,
            }

    async def authorize_plan(
        self,
        plan_id: str,
        authorized_by: str,
        reason: str,
        decision_repo: DecisionRepository,
        plan_repo: ActionPlanRepository,
        audit_repo: AuditRepository,
        event_repo: EventRepository,
    ) -> dict[str, Any]:
        """Authorize an action plan for execution."""
        plan_record = await plan_repo.get_by_id(plan_id)
        if plan_record is None:
            raise ValueError(f"Action plan {plan_id} not found")

        if plan_record.status != PlanStatus.AWAITING_AUTHORIZATION:
            raise ValueError(
                f"Plan {plan_id} is not awaiting authorization "
                f"(current: {plan_record.status.value})"
            )

        # Record authorization
        auth = self._decision_manager.create_authorization(
            plan_id, AuthorizationDecision.APPROVED, authorized_by, reason
        )
        await plan_repo.save_authorization(auth)
        await plan_repo.update_status(plan_id, PlanStatus.AUTHORIZED)

        # Transition decision
        await decision_repo.transition(
            str(plan_record.decision_id),
            DecisionStatus.AUTHORIZED,
            reason=f"Authorized by {authorized_by}: {reason}",
            actor=authorized_by,
        )

        await audit_repo.log(
            station_id=plan_record.station_id,
            correlation_id="",
            actor=authorized_by,
            action="plan_authorized",
            resource_type="action_plan",
            resource_id=plan_id,
            details={"reason": reason},
        )

        await self._broadcast_ws({
            "type": "plan_authorized",
            "plan_id": plan_id,
            "authorized_by": authorized_by,
        })

        # Reconstruct plan for execution
        plan = ActionPlan(
            plan_id=str(plan_record.plan_id),
            trigger_event_id=str(plan_record.trigger_event_id),
            decision_id=str(plan_record.decision_id),
            station_id=plan_record.station_id,
            status=PlanStatus.AUTHORIZED,
            reason=plan_record.reason,
            actions=[],  # Will be filled from JSON
            projected_reserve_kwh=plan_record.projected_reserve_kwh,
            required_reserve_kwh=plan_record.required_reserve_kwh,
            safety_status=plan_record.safety_status,
            requires_authorization=plan_record.requires_authorization,
            is_emergency=plan_record.is_emergency,
            created_at=plan_record.created_at,
            expires_at=plan_record.expires_at,
        )

        # Execute
        decision_id = str(plan_record.decision_id)
        decision_record = await decision_repo.get_by_id(decision_id)

        execution_result = await self._execute_plan(
            plan, None, event_repo, decision_repo, plan_repo, audit_repo,
            decision_id_override=decision_id,
        )

        return {
            "plan_id": plan_id,
            "status": "authorized_and_executing",
            "authorized_by": authorized_by,
            "execution": execution_result,
        }

    async def reject_plan(
        self,
        plan_id: str,
        rejected_by: str,
        reason: str,
        decision_repo: DecisionRepository,
        plan_repo: ActionPlanRepository,
        audit_repo: AuditRepository,
    ) -> dict[str, Any]:
        """Reject an action plan."""
        plan_record = await plan_repo.get_by_id(plan_id)
        if plan_record is None:
            raise ValueError(f"Action plan {plan_id} not found")

        if plan_record.status != PlanStatus.AWAITING_AUTHORIZATION:
            raise ValueError(
                f"Plan {plan_id} is not awaiting authorization "
                f"(current: {plan_record.status.value})"
            )

        # Record rejection
        auth = self._decision_manager.create_authorization(
            plan_id, AuthorizationDecision.REJECTED, rejected_by, reason
        )
        await plan_repo.save_authorization(auth)
        await plan_repo.update_status(plan_id, PlanStatus.REJECTED)

        # Transition decision
        await decision_repo.transition(
            str(plan_record.decision_id),
            DecisionStatus.REJECTED,
            reason=f"Rejected by {rejected_by}: {reason}",
            actor=rejected_by,
        )

        await audit_repo.log(
            station_id=plan_record.station_id,
            correlation_id="",
            actor=rejected_by,
            action="plan_rejected",
            resource_type="action_plan",
            resource_id=plan_id,
            details={"reason": reason},
        )

        await self._broadcast_ws({
            "type": "plan_rejected",
            "plan_id": plan_id,
            "rejected_by": rejected_by,
            "reason": reason,
        })

        return {
            "plan_id": plan_id,
            "status": "rejected",
            "rejected_by": rejected_by,
            "reason": reason,
        }

    async def _execute_plan(
        self,
        plan: ActionPlan,
        decision: Decision | None,
        event_repo: EventRepository,
        decision_repo: DecisionRepository,
        plan_repo: ActionPlanRepository,
        audit_repo: AuditRepository,
        decision_id_override: str | None = None,
    ) -> dict[str, Any]:
        """Send an authorized plan to M08 for execution and verify."""
        decision_id = decision_id_override or (decision.decision_id if decision else "")
        station_id = plan.station_id

        try:
            # Transition: AUTHORIZED → EXECUTING
            await decision_repo.transition(
                decision_id,
                DecisionStatus.EXECUTING,
                reason="Sending plan to M08 for execution",
            )
            await plan_repo.update_status(plan.plan_id, PlanStatus.EXECUTING)

            await self._broadcast_ws({
                "type": "execution_started",
                "plan_id": plan.plan_id,
                "decision_id": decision_id,
            })

            # Send to M08
            exec_result = await self._clients.execution.execute_plan({
                "plan_id": plan.plan_id,
                "station_id": station_id,
                "actions": [a.model_dump(mode="json") for a in plan.actions] if plan.actions else [],
                "actions_count": len(plan.actions),
            })

            if exec_result.status != "success":
                raise RuntimeError(f"Execution failed: {exec_result.error_message}")

            execution_id = exec_result.data.get("execution_id", "unknown")

            # Transition: EXECUTING → VERIFYING
            await decision_repo.transition(
                decision_id,
                DecisionStatus.VERIFYING,
                reason="Verifying execution results",
            )

            # Verify with M08
            verify_result = await self._clients.execution.verify_execution(execution_id)

            # Transition: VERIFYING → COMPLETED
            await decision_repo.transition(
                decision_id,
                DecisionStatus.COMPLETED,
                reason="Execution verified successfully",
            )
            await plan_repo.update_status(plan.plan_id, PlanStatus.COMPLETED)

            await audit_repo.log(
                station_id=station_id,
                correlation_id="",
                actor="orchestrator",
                action="execution_completed",
                resource_type="action_plan",
                resource_id=plan.plan_id,
                details={"execution_id": execution_id, "verification": verify_result.data},
            )

            await self._broadcast_ws({
                "type": "execution_completed",
                "plan_id": plan.plan_id,
                "decision_id": decision_id,
                "execution_id": execution_id,
            })

            # Publish to Redis
            if self._publisher:
                await self._publisher.publish_execution_result({
                    "plan_id": plan.plan_id,
                    "execution_id": execution_id,
                    "status": "completed",
                    "verification": verify_result.data,
                })

            return {
                "execution_id": execution_id,
                "status": "completed",
                "verification": verify_result.data,
            }

        except Exception as exc:
            await logger.aerror(
                "Plan execution failed",
                plan_id=plan.plan_id,
                error=str(exc),
            )

            await decision_repo.transition(
                decision_id,
                DecisionStatus.EXECUTION_FAILED,
                reason=f"Execution failed: {str(exc)}",
            )
            await plan_repo.update_status(plan.plan_id, PlanStatus.FAILED)

            await audit_repo.log(
                station_id=station_id,
                correlation_id="",
                actor="orchestrator",
                action="execution_failed",
                resource_type="action_plan",
                resource_id=plan.plan_id,
                details={"error": str(exc)},
                status="error",
            )

            return {
                "status": "failed",
                "error": str(exc),
            }

    async def _broadcast_ws(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all WebSocket connections."""
        if self._ws_manager:
            try:
                await self._ws_manager.broadcast(message)
            except Exception as exc:
                await logger.awarning("WebSocket broadcast failed", error=str(exc))
