"""
Frost OS Module 01 — M04 Forecast Intelligence Client.

Communicates with Module 04 for weather and generation forecasts.
"""

from __future__ import annotations

from app.clients.base_client import BaseModuleClient
from app.config.settings import Settings
from app.models.decision import ModuleResponse
from app.models.event import StationEvent


class ForecastClient(BaseModuleClient):
    """REST client for M04 Forecast Intelligence."""

    MODULE_NAME = "forecast"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings.forecast_service_url, settings)

    async def get_forecast(
        self, station_id: str, hours: int = 24
    ) -> ModuleResponse:
        """Retrieve energy generation forecast."""
        return await self._request(
            "GET",
            f"/forecast/station/{station_id}",
            params={"hours": hours},
        )

    async def get_weather_forecast(self, station_id: str) -> ModuleResponse:
        """Retrieve weather forecast for a station."""
        return await self._request("GET", f"/forecast/station/{station_id}/weather")


class MockForecastClient(ForecastClient):
    """Mock M04 client — predicts continued wind decline."""

    async def get_forecast(
        self, station_id: str, hours: int = 24
    ) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "forecast_hours": hours,
                "wind_forecast": [
                    {"hour": 1, "wind_kw": 65.0, "confidence": 0.9},
                    {"hour": 2, "wind_kw": 55.0, "confidence": 0.85},
                    {"hour": 3, "wind_kw": 45.0, "confidence": 0.8},
                    {"hour": 6, "wind_kw": 30.0, "confidence": 0.7},
                    {"hour": 12, "wind_kw": 25.0, "confidence": 0.6},
                    {"hour": 24, "wind_kw": 40.0, "confidence": 0.45},
                ],
                "solar_forecast": [
                    {"hour": 1, "solar_kw": 12.0, "confidence": 0.85},
                    {"hour": 6, "solar_kw": 5.0, "confidence": 0.7},
                    {"hour": 12, "solar_kw": 0.0, "confidence": 0.9},
                    {"hour": 24, "solar_kw": 10.0, "confidence": 0.5},
                ],
                "trend": "declining",
                "lowest_generation_kw": 25.0,
                "lowest_generation_hour": 12,
                "recovery_expected_hour": 24,
                "confidence": 0.72,
            },
        )

    async def get_weather_forecast(self, station_id: str) -> ModuleResponse:
        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="success",
            data={
                "station_id": station_id,
                "temperature_c": -28.0,
                "wind_speed_ms": 8.5,
                "wind_direction_deg": 220,
                "precipitation": "light_snow",
                "visibility_km": 2.0,
                "icing_risk": "moderate",
                "storm_warning": False,
                "forecast_period_hours": 24,
            },
        )
