"""
Frost OS Module 01 — M03 Energy Intelligence Client.

Communicates with Module 03 for energy status, generation analysis,
and consumption data.
"""

from __future__ import annotations

from app.clients.base_client import BaseModuleClient
from app.config.settings import Settings
from app.models.decision import ModuleResponse
from app.models.event import StationEvent


class EnergyClient(BaseModuleClient):
    """REST client for M03 Energy Intelligence."""

    MODULE_NAME = "energy"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.energy_service_url, settings)

    async def get_energy_status(self, station_id: str) -> ModuleResponse:
        """Retrieve current energy status for a station."""
        return await self._request("GET", f"/energy/station/{station_id}/status")

    async def analyze_generation_event(
        self, station_id: str, event: StationEvent
    ) -> ModuleResponse:
        """Analyze a generation-related event."""
        return await self._request(
            "POST",
            f"/energy/station/{station_id}/analyze",
            json_data=event.model_dump(mode="json"),
        )


class MockEnergyClient(EnergyClient):
    """Mock M03 client for standalone development and testing."""

    async def get_energy_status(self, station_id: str) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "generation": {
                    "wind_kw": 70.0,
                    "solar_kw": 15.0,
                    "hydrogen_fuel_cell_kw": 0.0,
                    "total_generation_kw": 85.0,
                },
                "consumption": {
                    "total_demand_kw": 105.0,
                    "deficit_kw": 20.0,
                },
                "storage": {
                    "battery_kwh": 450.0,
                    "battery_capacity_kwh": 600.0,
                    "battery_soc_pct": 75.0,
                    "hydrogen_kg": 120.0,
                    "hydrogen_capacity_kg": 200.0,
                },
                "grid_status": "deficit",
            },
        )

    async def analyze_generation_event(
        self, station_id: str, event: StationEvent
    ) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "analysis": {
                    "event_type": event.event_type.value,
                    "previous_generation_kw": 180.0,
                    "current_generation_kw": 70.0,
                    "drop_kw": 110.0,
                    "drop_pct": 61.1,
                    "cause_assessment": "Significant wind generation decline detected",
                    "battery_runway_hours": 22.5,
                    "immediate_risk": False,
                    "requires_load_adjustment": True,
                },
            },
        )
