"""
Frost OS Module 01 — Workflow Engine.

Registry-based workflow dispatch. Workflows are registered by name
and invoked by the orchestrator. Each workflow receives a StationEvent
and module clients, and returns a DecisionContext.

Extensible: register new workflows via @workflow_registry.register
or explicit WorkflowRegistry.register() calls.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol

import structlog

from app.models.event import StationEvent
from app.models.decision import DecisionContext

logger = structlog.get_logger(__name__)


class WorkflowHandler(Protocol):
    """Protocol for workflow handler functions."""

    async def __call__(
        self,
        event: StationEvent,
        context: DecisionContext,
        clients: Any,
    ) -> DecisionContext:
        ...


class WorkflowRegistry:
    """
    Registry for workflow handlers.

    Workflows are registered by name and looked up at dispatch time.
    This enables extensibility without modifying the orchestrator.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, WorkflowHandler] = {}

    def register(self, name: str, handler: WorkflowHandler) -> None:
        """Register a workflow handler by name."""
        if name in self._handlers:
            logger.warning("Overwriting existing workflow handler", name=name)
        self._handlers[name] = handler
        logger.info("Registered workflow handler", name=name)

    def get(self, name: str) -> WorkflowHandler | None:
        """Look up a workflow handler by name."""
        return self._handlers.get(name)

    def has(self, name: str) -> bool:
        """Check if a workflow is registered."""
        return name in self._handlers

    def list_workflows(self) -> list[str]:
        """Return all registered workflow names."""
        return list(self._handlers.keys())


class WorkflowEngine:
    """
    Executes workflows by looking them up in the registry.

    The engine is responsible for dispatch — the actual workflow
    logic lives in individual workflow handlers.
    """

    def __init__(self, registry: WorkflowRegistry) -> None:
        self._registry = registry

    async def execute(
        self,
        workflow_name: str,
        event: StationEvent,
        context: DecisionContext,
        clients: Any,
    ) -> DecisionContext:
        """
        Execute a named workflow.

        Args:
            workflow_name: Registered workflow name
            event: The triggering station event
            context: Decision context to populate
            clients: Module client container

        Returns:
            Populated DecisionContext with module responses

        Raises:
            ValueError: If workflow_name is not registered
        """
        handler = self._registry.get(workflow_name)
        if handler is None:
            raise ValueError(
                f"Unknown workflow: '{workflow_name}'. "
                f"Registered workflows: {self._registry.list_workflows()}"
            )

        await logger.ainfo(
            "Executing workflow",
            workflow=workflow_name,
            event_id=event.event_id,
            correlation_id=context.correlation_id,
        )

        result = await handler(event, context, clients)

        await logger.ainfo(
            "Workflow completed",
            workflow=workflow_name,
            event_id=event.event_id,
            degraded_modules=result.degraded_modules,
        )

        return result


# ── Global Registry Singleton ─────────────────────────────────────────

workflow_registry = WorkflowRegistry()
