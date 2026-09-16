"""
Frost OS Module 01 — M02 Mission Intelligence Client.

Communicates with Module 02 to retrieve active missions,
mission priorities, and workload information.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.clients.base_client import BaseModuleClient
from app.config.settings import Settings
from app.models.decision import ModuleResponse
from app.models.event import StationEvent


class MissionClient(BaseModuleClient):
    """REST client for M02 Mission Intelligence."""

    MODULE_NAME = "mission"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.mission_service_url, settings)

    async def get_active_missions(self, station_id: str) -> ModuleResponse:
        """Retrieve all active missions for a station."""
        return await self._request("GET", f"/missions/station/{station_id}/active")

    async def get_mission_priorities(self, station_id: str) -> ModuleResponse:
        """Retrieve mission priorities and workload classifications."""
        return await self._request("GET", f"/missions/station/{station_id}/priorities")

    async def analyze_mission_impact(
        self, station_id: str, event: StationEvent
    ) -> ModuleResponse:
        """Analyze impact of an event on active missions."""
        return await self._request(
            "POST",
            f"/missions/station/{station_id}/impact-analysis",
            json_data=event.model_dump(mode="json"),
        )


class MockMissionClient(MissionClient):
    """Mock M02 client for standalone development and testing."""

    async def get_active_missions(self, station_id: str) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "active_missions": [
                    {
                        "mission_id": "MSN-001",
                        "name": "Life Support Systems",
                        "priority": "P1",
                        "power_requirement_kw": 45.0,
                        "critical": True,
                        "can_reduce": False,
                    },
                    {
                        "mission_id": "MSN-002",
                        "name": "Communications Array",
                        "priority": "P2",
                        "power_requirement_kw": 25.0,
                        "critical": True,
                        "can_reduce": True,
                        "minimum_kw": 15.0,
                    },
                    {
                        "mission_id": "MSN-003",
                        "name": "Atmospheric Data Processing",
                        "priority": "P3",
                        "power_requirement_kw": 35.0,
                        "critical": False,
                        "can_reduce": True,
                        "minimum_kw": 10.0,
                    },
                ],
                "total_demand_kw": 105.0,
            },
        )

    async def get_mission_priorities(self, station_id: str) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "priority_order": ["P1", "P2", "P3"],
                "non_reducible_kw": 45.0,
                "reducible_kw": 60.0,
                "total_kw": 105.0,
            },
        )

    async def analyze_mission_impact(
        self, station_id: str, event: StationEvent
    ) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "impact_assessment": {
                    "affected_missions": ["MSN-002", "MSN-003"],
                    "p1_impact": "none",
                    "p2_impact": "potential_degradation",
                    "p3_impact": "can_defer",
                    "recommendation": "Reduce P3 workloads first, maintain P1/P2",
                },
            },
        )
