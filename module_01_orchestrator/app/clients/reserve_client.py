"""
Frost OS Module 01 — M07 Safety + Reserve Intelligence Client.

Communicates with Module 07 for reserve validation and safety checks.
M07 determines whether an action plan meets reserve requirements
and safety constraints. If M07 marks an event as emergency,
Module 01 MUST NOT override that — safeguard execution proceeds
immediately without human authorization.
"""

from __future__ import annotations

from typing import Any

from app.clients.base_client import BaseModuleClient
from app.config.settings import Settings
from app.models.decision import ModuleResponse


class ReserveClient(BaseModuleClient):
    """REST client for M07 Safety + Reserve Intelligence."""

    MODULE_NAME = "reserve"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.reserve_service_url, settings)

    async def validate_reserves(
        self, station_id: str, plan_data: dict[str, Any]
    ) -> ModuleResponse:
        """Validate that a plan maintains required energy reserves."""
        return await self._request(
            "POST",
            f"/reserve/station/{station_id}/validate",
            json_data=plan_data,
        )

    async def check_safety(
        self, station_id: str, plan_data: dict[str, Any]
    ) -> ModuleResponse:
        """
        Perform safety validation on a plan.

        If the response includes is_emergency=True, Module 01 MUST
        allow immediate execution without human authorization.
        """
        return await self._request(
            "POST",
            f"/reserve/station/{station_id}/safety-check",
            json_data=plan_data,
        )


class MockReserveClient(ReserveClient):
    """Mock M07 client — validates reserves and passes safety."""

    async def validate_reserves(
        self, station_id: str, plan_data: dict[str, Any]
    ) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "reserve_validation": {
                    "is_valid": True,
                    "projected_reserve_kwh": 410.0,
                    "required_reserve_kwh": 200.0,
                    "reserve_margin_kwh": 210.0,
                    "reserve_margin_pct": 105.0,
                    "min_48h_reserve_met": True,
                    "details": "Projected reserves exceed 48-hour minimum requirement",
                },
            },
        )

    async def check_safety(
        self, station_id: str, plan_data: dict[str, Any]
    ) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "safety_check": {
                    "is_safe": True,
                    "is_emergency": False,
                    "safety_status": "PASSED",
                    "constraints_met": [
                        "life_support_power_maintained",
                        "communications_maintained",
                        "reserve_minimum_met",
                        "temperature_safety_maintained",
                    ],
                    "warnings": [],
                    "overrides": [],
                },
            },
        )
