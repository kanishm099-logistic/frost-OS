"""
Frost OS Module 01 — M06 Optimization Intelligence Client.

Communicates with Module 06 for load optimization and
resource allocation proposals.
"""

from __future__ import annotations

from typing import Any

from app.clients.base_client import BaseModuleClient
from app.config.settings import Settings
from app.models.decision import ModuleResponse


class OptimizerClient(BaseModuleClient):
    """REST client for M06 Optimization Intelligence."""

    MODULE_NAME = "optimizer"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.optimizer_service_url, settings)

    async def optimize_allocation(
        self, station_id: str, context: dict[str, Any]
    ) -> ModuleResponse:
        """Request optimized resource allocation."""
        return await self._request(
            "POST",
            f"/optimizer/station/{station_id}/optimize",
            json_data=context,
        )


class MockOptimizerClient(OptimizerClient):
    """Mock M06 client — returns proposed load allocation."""

    async def optimize_allocation(
        self, station_id: str, context: dict[str, Any]
    ) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "optimization_result": {
                    "strategy": "load_shedding_with_storage",
                    "actions": [
                        {
                            "action_type": "REDUCE_LOAD",
                            "target": "Atmospheric Data Processing (P3)",
                            "description": "Reduce P3 workload by 40% to decrease demand by 14 kW",
                            "parameters": {
                                "current_kw": 35.0,
                                "target_kw": 21.0,
                                "reduction_kw": 14.0,
                            },
                            "priority": 1,
                            "estimated_impact_kwh": 14.0,
                            "reversible": True,
                        },
                        {
                            "action_type": "ACTIVATE_STORAGE",
                            "target": "Battery Storage System",
                            "description": "Draw 6 kW from battery storage to cover remaining deficit",
                            "parameters": {
                                "discharge_rate_kw": 6.0,
                                "estimated_duration_hours": 6.0,
                            },
                            "priority": 2,
                            "estimated_impact_kwh": 36.0,
                            "reversible": True,
                        },
                        {
                            "action_type": "ACTIVATE_DEICING",
                            "target": "Wind Turbine WIND-TURBINE-01",
                            "description": "Activate de-icing system to restore turbine efficiency",
                            "parameters": {
                                "estimated_recovery_pct": 25.0,
                                "deicing_power_kw": 5.0,
                                "estimated_duration_minutes": 45,
                            },
                            "priority": 3,
                            "estimated_impact_kwh": -3.75,
                            "reversible": True,
                        },
                    ],
                    "projected_balance_kw": 0.0,
                    "projected_reserve_kwh": 410.0,
                    "confidence": 0.85,
                },
            },
        )
