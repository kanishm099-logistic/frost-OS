"""
Frost OS Module 01 — M05 Diagnostic Intelligence Client.

Communicates with Module 05 for equipment diagnostics and
anomaly analysis.
"""

from __future__ import annotations

from app.clients.base_client import BaseModuleClient
from app.config.settings import Settings
from app.models.decision import ModuleResponse
from app.models.event import StationEvent


class DiagnosticClient(BaseModuleClient):
    """REST client for M05 Diagnostic Intelligence."""

    MODULE_NAME = "diagnostic"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.diagnostic_service_url, settings)

    async def diagnose_equipment(
        self, station_id: str, event: StationEvent
    ) -> ModuleResponse:
        """Request equipment diagnostics for an event."""
        return await self._request(
            "POST",
            f"/diagnostics/station/{station_id}/diagnose",
            json_data=event.model_dump(mode="json"),
        )

    async def get_equipment_health(self, station_id: str) -> ModuleResponse:
        """Retrieve overall equipment health status."""
        return await self._request("GET", f"/diagnostics/station/{station_id}/health")


class MockDiagnosticClient(DiagnosticClient):
    """Mock M05 client — reports icing risk on turbines."""

    async def diagnose_equipment(
        self, station_id: str, event: StationEvent
    ) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "diagnostics": {
                    "equipment_id": "WIND-TURBINE-01",
                    "equipment_type": "wind_turbine",
                    "status": "degraded",
                    "issues": [
                        {
                            "issue_id": "DIAG-001",
                            "type": "icing",
                            "severity": "HIGH",
                            "description": "Ice accumulation detected on turbine blades",
                            "estimated_efficiency_loss_pct": 35.0,
                            "recommended_action": "Activate de-icing system",
                        },
                    ],
                    "overall_health_score": 0.65,
                    "maintenance_recommended": True,
                    "estimated_repair_hours": 2.0,
                },
            },
        )

    async def get_equipment_health(self, station_id: str) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "equipment_summary": {
                    "total_units": 12,
                    "healthy": 9,
                    "degraded": 2,
                    "failed": 1,
                    "overall_health": 0.78,
                },
            },
        )
