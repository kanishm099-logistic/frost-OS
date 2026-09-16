"""
Frost OS Module 01 — M08 Execution + Verification Client.

Communicates with Module 08 to send approved action plans for
hardware execution and to verify execution results.

Module 08 translates descriptive action plans into actual
hardware commands — Module 01 never sends raw hardware commands.
"""

from __future__ import annotations

from typing import Any

from app.clients.base_client import BaseModuleClient
from app.config.settings import Settings
from app.models.decision import ModuleResponse


class ExecutionClient(BaseModuleClient):
    """REST client for M08 Execution + Verification."""

    MODULE_NAME = "execution"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.execution_service_url, settings)

    async def execute_plan(self, plan_data: dict[str, Any]) -> ModuleResponse:
        """Send an approved action plan for execution."""
        return await self._request(
            "POST",
            "/execution/execute",
            json_data=plan_data,
        )

    async def verify_execution(self, execution_id: str) -> ModuleResponse:
        """Verify the results of an execution."""
        return await self._request(
            "GET",
            f"/execution/{execution_id}/verify",
        )


class MockExecutionClient(ExecutionClient):
    """Mock M08 client — simulates successful execution."""

    async def execute_plan(self, plan_data: dict[str, Any]) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "execution_id": "EXEC-001",
                "plan_id": plan_data.get("plan_id", "unknown"),
                "status": "executing",
                "actions_initiated": plan_data.get("actions_count", 3),
                "estimated_completion_minutes": 5,
            },
        )

    async def verify_execution(self, execution_id: str) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "execution_id": execution_id,
                "verification": {
                    "status": "completed",
                    "all_actions_successful": True,
                    "results": [
                        {
                            "action_type": "REDUCE_LOAD",
                            "target": "Atmospheric Data Processing (P3)",
                            "status": "completed",
                            "actual_reduction_kw": 14.0,
                        },
                        {
                            "action_type": "ACTIVATE_STORAGE",
                            "target": "Battery Storage System",
                            "status": "completed",
                            "actual_discharge_kw": 6.0,
                        },
                        {
                            "action_type": "ACTIVATE_DEICING",
                            "target": "Wind Turbine WIND-TURBINE-01",
                            "status": "completed",
                            "deicing_active": True,
                        },
                    ],
                    "post_execution_generation_kw": 88.0,
                    "post_execution_demand_kw": 91.0,
                    "post_execution_deficit_kw": 3.0,
                },
            },
        )
