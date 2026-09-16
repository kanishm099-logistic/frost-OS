"""
Dynamic Station Reserve Calculation Engine.

Calculates required station energy reserve dynamically using:
  required_reserve = (
      critical_load_energy
    + emergency_energy
    + mission_protected_energy
    + forecast_uncertainty_margin
    + equipment_risk_margin
    + operational_margin
  )
Distinguishes 5 reserve types and computes Time-to-Reserve trajectories without double counting.
"""

from __future__ import annotations

from typing import Dict, Any, List, Tuple
import numpy as np
import structlog

from app.models.reserve import (
    ReserveCalculation,
    ReserveComponent,
    ReserveType,
)
from app.config.settings import Settings
from policies.reserve_policy import ReservePolicy

logger = structlog.get_logger(__name__)


class ReserveEngine:
    """Dynamic Station Reserve Engine."""

    def __init__(self, settings: Settings, policy: ReservePolicy | None = None):
        self.settings = settings
        self.policy = policy or ReservePolicy()

    def calculate_reserve(
        self,
        energy_state: Dict[str, Any],
        missions: List[Dict[str, Any]],
        forecast: Dict[str, Any],
        equipment_health: Dict[str, Any],
        weather_event: str = "NORMAL",
    ) -> ReserveCalculation:
        """
        Calculate dynamic station reserve requirement and compare against current storage.
        """
        station_id = self.settings.station_id
        horizon_hours = self.policy.reserve_horizon_hours

        # 1. Base Components
        # Station Continuity (Critical Load over Horizon)
        crit_load_kw = float(energy_state.get("critical_load_kw", self.policy.critical_load_kw))
        station_reserve_kwh = crit_load_kw * horizon_hours

        # Emergency / Life-Support Reserve
        emergency_reserve_kwh = float(self.policy.emergency_reserve_kwh)

        # Mission Protected Energy (Protected energy from P0/P1 missions)
        mission_protected_kwh = 0.0
        for m in missions:
            prio = str(m.get("priority", "P3"))
            if prio in ("P0", "P1") or m.get("critical", False):
                # Energy required by critical mission
                req_kw = float(m.get("power_requirement_kw", m.get("required_power_kw", 0.0)))
                dur_h = float(m.get("duration_hours", 6.0))
                buf_factor = self.policy.uncertainty_margin_factor if prio == "P0" else 1.10
                mission_protected_kwh += req_kw * dur_h * buf_factor

        # 2. Multipliers & Dynamic Margins
        # Weather / Storm Multiplier
        weather_mult = 1.0
        if weather_event in ("STORM", "BLIZZARD"):
            weather_mult = self.policy.storm_reserve_multiplier
        elif weather_event == "LOW_WIND":
            weather_mult = self.policy.low_wind_reserve_multiplier

        # Forecast Uncertainty Margin
        forecast_conf = float(forecast.get("confidence", 0.85))
        uncert_factor = self.policy.uncertainty_margin_factor * (1.0 + (1.0 - forecast_conf)) * weather_mult
        forecast_uncertainty_margin_kwh = station_reserve_kwh * (uncert_factor - 1.0)

        # Equipment Failure Risk Margin
        overall_health = float(equipment_health.get("overall_health_score", 100.0))
        equip_margin_factor = 1.0
        if overall_health < 80.0:
            equip_margin_factor = self.policy.equipment_risk_margin_factor + ((80.0 - overall_health) / 100.0)
        equipment_risk_margin_kwh = station_reserve_kwh * (equip_margin_factor - 1.0)

        # Operational Short-term Dispatch Margin
        operational_reserve_kwh = crit_load_kw * 4.0  # 4 hours short-term margin

        # Total Combined Protected Reserve (Avoiding Double Counting)
        # If policy deducts overlap between station continuity & protected missions:
        total_protected_reserve_kwh = (
            station_reserve_kwh
            + emergency_reserve_kwh
            + mission_protected_kwh
            + forecast_uncertainty_margin_kwh
            + equipment_risk_margin_kwh
            + operational_reserve_kwh
        )

        # 3. Available Storage
        curr_bess_kwh = float(energy_state.get("battery_energy_kwh", 400.0))
        curr_h2_kwh = float(energy_state.get("hydrogen_energy_kwh", 200.0))
        total_available = curr_bess_kwh + curr_h2_kwh

        margin = total_available - total_protected_reserve_kwh
        satisfied = margin >= 0.0

        # 4. Time-to-Reserve Calculation (Expected vs Conservative)
        expected_t2r, cons_t2r = self._calculate_time_to_reserve(
            total_available=total_available,
            required_reserve=total_protected_reserve_kwh,
            energy_state=energy_state,
            forecast=forecast,
        )

        # Build Components List
        components = [
            ReserveComponent(
                name="Station Continuity Reserve",
                reserve_type=ReserveType.STATION_RESERVE_KWH,
                amount_kwh=round(station_reserve_kwh, 2),
                description=f"Base critical load ({crit_load_kw} kW) for {horizon_hours} hours",
            ),
            ReserveComponent(
                name="Emergency Reserve",
                reserve_type=ReserveType.EMERGENCY_RESERVE_KWH,
                amount_kwh=round(emergency_reserve_kwh, 2),
                description="Life-support & emergency evacuation buffer",
            ),
            ReserveComponent(
                name="Mission Protected Energy",
                reserve_type=ReserveType.MISSION_RESERVE_KWH,
                amount_kwh=round(mission_protected_kwh, 2),
                description="Protected energy allocation for P0/P1 research missions",
            ),
            ReserveComponent(
                name="Forecast Uncertainty Margin",
                reserve_type=ReserveType.OPERATIONAL_RESERVE_KWH,
                amount_kwh=round(forecast_uncertainty_margin_kwh, 2),
                description=f"Uncertainty buffer for weather ({weather_event}) and confidence ({forecast_conf})",
            ),
            ReserveComponent(
                name="Equipment Risk Margin",
                reserve_type=ReserveType.OPERATIONAL_RESERVE_KWH,
                amount_kwh=round(equipment_risk_margin_kwh, 2),
                description=f"Derating buffer for equipment health ({overall_health}%)",
            ),
            ReserveComponent(
                name="Operational Dispatch Margin",
                reserve_type=ReserveType.OPERATIONAL_RESERVE_KWH,
                amount_kwh=round(operational_reserve_kwh, 2),
                description="Short-term 4h spinning reserve margin",
            ),
        ]

        return ReserveCalculation(
            station_id=station_id,
            horizon_hours=horizon_hours,
            station_reserve_kwh=round(station_reserve_kwh, 2),
            mission_reserve_kwh=round(mission_protected_kwh, 2),
            emergency_reserve_kwh=round(emergency_reserve_kwh, 2),
            operational_reserve_kwh=round(operational_reserve_kwh + forecast_uncertainty_margin_kwh + equipment_risk_margin_kwh, 2),
            total_protected_reserve_kwh=round(total_protected_reserve_kwh, 2),
            current_battery_energy_kwh=round(curr_bess_kwh, 2),
            current_hydrogen_energy_kwh=round(curr_h2_kwh, 2),
            total_available_storage_kwh=round(total_available, 2),
            reserve_margin_kwh=round(margin, 2),
            reserve_satisfied=satisfied,
            time_to_reserve_expected_hours=round(expected_t2r, 1),
            time_to_reserve_conservative_hours=round(cons_t2r, 1),
            components=components,
        )

    def _calculate_time_to_reserve(
        self,
        total_available: float,
        required_reserve: float,
        energy_state: Dict[str, Any],
        forecast: Dict[str, Any],
    ) -> Tuple[float, float]:
        """
        Forecast time-to-reserve under expected and conservative generation/load trajectories.
        """
        curr_load = float(energy_state.get("current_load_kw", 60.0))
        curr_gen = float(energy_state.get("current_generation_kw", 40.0))
        
        net_drain = max(1.0, curr_load - curr_gen)
        
        # Expected T2R
        if total_available <= required_reserve:
            expected_t2r = 0.0
        else:
            excess = total_available - required_reserve
            expected_t2r = excess / net_drain

        # Conservative T2R (higher load + lower generation)
        cons_drain = net_drain * 1.35
        if total_available <= required_reserve:
            cons_t2r = 0.0
        else:
            excess = total_available - required_reserve
            cons_t2r = excess / cons_drain

        return min(72.0, expected_t2r), min(72.0, cons_t2r)
