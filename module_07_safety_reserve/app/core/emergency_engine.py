"""
Emergency Condition Detection Engine.

Deterministic, zero-LLM protection engine that monitors telemetry and state
for dangerous hardware conditions (thermal runaway, overpressure, power loss,
critical SOC depletion).
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional
import structlog

from app.models.safety_decision import SafetyDecisionStatus
from app.config.settings import Settings

logger = structlog.get_logger(__name__)


class EmergencyEvent(Exception):
    """Exception raised when a critical emergency condition is detected."""
    def __init__(self, condition: str, description: str, details: Dict[str, Any]):
        self.condition = condition
        self.description = description
        self.details = details
        super().__init__(f"EMERGENCY: {condition} - {description}")


class EmergencyEngine:
    """Deterministic Emergency Detection Engine."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def check_emergency_conditions(
        self,
        energy_state: Dict[str, Any],
        equipment_health: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Check telemetry and health states for hardware emergency conditions.
        Returns emergency details dictionary if triggered, else None.
        """
        battery_temp = float(energy_state.get("battery_temperature_c", 20.0))
        if battery_temp >= self.settings.critical_battery_temp_c:
            logger.critical("Battery thermal emergency detected!", temperature_c=battery_temp)
            return {
                "triggered": True,
                "condition": "BATTERY_THERMAL_OVERTEMPERATURE",
                "description": f"Battery temperature {battery_temp}°C exceeds critical threshold {self.settings.critical_battery_temp_c}°C",
                "protective_action": "ISOLATE_BATTERY_SYSTEM",
                "details": {"battery_temperature_c": battery_temp, "threshold": self.settings.critical_battery_temp_c},
            }

        hydrogen_pressure = float(energy_state.get("hydrogen_pressure_bar", 200.0))
        if hydrogen_pressure >= self.settings.maximum_hydrogen_pressure_bar:
            logger.critical("Hydrogen overpressure emergency detected!", pressure_bar=hydrogen_pressure)
            return {
                "triggered": True,
                "condition": "HYDROGEN_OVERPRESSURE",
                "description": f"Hydrogen pressure {hydrogen_pressure} bar exceeds safe limit {self.settings.maximum_hydrogen_pressure_bar} bar",
                "protective_action": "VENT_HYDROGEN_LINE",
                "details": {"hydrogen_pressure_bar": hydrogen_pressure, "threshold": self.settings.maximum_hydrogen_pressure_bar},
            }

        battery_soc = float(energy_state.get("battery_soc_pct", 50.0))
        critical_soc = self.settings.critical_battery_soc_pct
        if battery_soc <= critical_soc:
            logger.critical("Critical battery SOC exhaustion detected!", battery_soc=battery_soc)
            return {
                "triggered": True,
                "condition": "CRITICAL_BATTERY_EXHAUSTION",
                "description": f"Battery SOC {battery_soc}% is at or below critical exhaustion limit {critical_soc}%",
                "protective_action": "SHED_ALL_NON_P0_LOADS",
                "details": {"battery_soc_pct": battery_soc, "threshold": critical_soc},
            }

        return None
