"""
Frost OS Module 03 — Energy Intelligence Agent.

Provides conversational query answering, situational explanations,
hypothetical load addition impact evaluations, and operational summaries
for Station Operators and Module 01 Orchestrator.
"""

from __future__ import annotations

import re
from typing import Any

import structlog

from app.core.energy_engine import EnergyEngine
from app.models.energy_state import EnergyState, EnergyStatus

logger = structlog.get_logger(__name__)


class EnergyAgent:
    """
    Intelligent agent interface for station energy telemetry and states.
    Produces deterministic, structured operational assessments and explanations.
    """

    def __init__(self, engine: EnergyEngine):
        self.engine = engine

    def query(self, station_id: str, question: str) -> dict[str, Any]:
        """
        Answer operational queries about the station's real-time energy state.
        """
        state = self.engine.get_latest_state(station_id)
        q_lower = question.lower()

        if state is None:
            return {
                "station_id": station_id,
                "answer": f"No telemetry or energy state snapshot is currently available for station '{station_id}'.",
                "intent": "UNKNOWN",
                "state_available": False,
            }

        # Check for hypothetical addition: "can we add 50 kW for 2 hours?"
        match_load = re.search(r"(\d+(?:\.\d+)?)\s*kw", q_lower)
        if ("can we" in q_lower or "add" in q_lower or "support" in q_lower) and match_load:
            add_kw = float(match_load.group(1))
            match_dur = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hour|hours)", q_lower)
            dur_h = float(match_dur.group(1)) if match_dur else 1.0
            return self.evaluate_load_addition(station_id, add_kw, dur_h)

        # Check for runway / storage queries
        if any(w in q_lower for w in ["runway", "how long", "battery", "storage", "hours left"]):
            return self._explain_runway(state)

        # Check for anomaly / alert queries
        if any(w in q_lower for w in ["alert", "anomaly", "problem", "warning", "issue", "bad data"]):
            return self._explain_alerts(state)

        # Check for generation / solar / wind queries
        if any(w in q_lower for w in ["solar", "wind", "generation", "renewable"]):
            return self._explain_generation(state)

        # Check for load / consumption queries
        if any(w in q_lower for w in ["load", "consumption", "power demand", "draw"]):
            return self._explain_load(state)

        # Default: General status summary
        return self._explain_status(state)

    def evaluate_load_addition(
        self,
        station_id: str,
        additional_kw: float,
        duration_hours: float = 1.0,
    ) -> dict[str, Any]:
        """
        Evaluate physical impact of adding a new electrical load to the station microgrid.
        Determines feasibility, new net power balance, and projected runway.
        """
        state = self.engine.get_latest_state(station_id)
        if state is None:
            return {
                "feasible": False,
                "verdict": "INFEASIBLE",
                "reason": "No active station energy state to evaluate against.",
            }

        curr_net = state.net_power_kw
        new_net = curr_net - additional_kw
        total_energy_needed_kwh = additional_kw * duration_hours
        usable_battery_kwh = state.battery.usable_energy_kwh

        # Assess feasibility
        if new_net >= 0:
            verdict = "FEASIBLE"
            reason = (
                f"Station currently has a {curr_net:+.1f} kW net surplus. "
                f"Adding {additional_kw:.1f} kW leaves a surplus of {new_net:+.1f} kW without drawing from battery."
            )
            projected_runway = state.battery.runway_hours
        else:
            # Deficit: requires battery or hydrogen discharge
            deficit_kw = abs(new_net)
            # Check maximum discharge power rating
            max_discharge_kw = state.battery.discharge_limit_kw
            if deficit_kw > max_discharge_kw:
                verdict = "INFEASIBLE"
                reason = (
                    f"Resulting deficit ({deficit_kw:.1f} kW) exceeds maximum battery discharge "
                    f"rate limit ({max_discharge_kw:.1f} kW)."
                )
                projected_runway = 0.0
            elif total_energy_needed_kwh > usable_battery_kwh:
                verdict = "INFEASIBLE"
                reason = (
                    f"Energy required ({total_energy_needed_kwh:.1f} kWh) exceeds usable battery "
                    f"capacity ({usable_battery_kwh:.1f} kWh above 20% reserve)."
                )
                projected_runway = round(usable_battery_kwh / deficit_kw, 2)
            else:
                projected_runway = round(usable_battery_kwh / deficit_kw, 2)
                if projected_runway < 2.0:
                    verdict = "MARGINAL"
                    reason = (
                        f"Load can be sustained for {duration_hours:.1f}h, but reduces battery runway to "
                        f"{projected_runway:.2f}h, below the 2.0h critical threshold."
                    )
                else:
                    verdict = "FEASIBLE"
                    reason = (
                        f"Battery can supply the {deficit_kw:.1f} kW draw. Projected battery runway "
                        f"will be {projected_runway:.2f} hours (requires {total_energy_needed_kwh:.1f} kWh of {usable_battery_kwh:.1f} kWh available)."
                    )

        return {
            "station_id": station_id,
            "additional_kw": additional_kw,
            "duration_hours": duration_hours,
            "current_net_power_kw": curr_net,
            "projected_net_power_kw": new_net,
            "usable_battery_kwh": usable_battery_kwh,
            "energy_needed_kwh": total_energy_needed_kwh,
            "projected_runway_hours": projected_runway,
            "verdict": verdict,
            "feasible": verdict == "FEASIBLE",
            "reason": reason,
        }

    def _explain_status(self, state: EnergyState) -> dict[str, Any]:
        """Generate high-level operational status explanation."""
        balance_desc = (
            f"surplus of {state.net_power_kw:+.1f} kW"
            if state.net_power_kw >= 0
            else f"deficit of {abs(state.net_power_kw):.1f} kW"
        )
        answer = (
            f"Station '{state.station_id}' is currently {state.status.value}. "
            f"Generating {state.generation.total_generation_kw:.1f} kW "
            f"(Solar: {state.generation.solar_kw:.1f} kW, Wind: {state.generation.wind_kw:.1f} kW) "
            f"against a total load of {state.load.total_load_kw:.1f} kW, resulting in a net {balance_desc}. "
            f"Battery SOC is {state.battery.soc_pct:.1f}% ({state.battery.usable_energy_kwh:.1f} kWh usable). "
            f"Active alerts: {len(state.active_alerts)}."
        )
        return {
            "station_id": state.station_id,
            "answer": answer,
            "intent": "STATUS",
            "status": state.status.value,
            "net_power_kw": state.net_power_kw,
            "generation_kw": state.generation.total_generation_kw,
            "load_kw": state.load.total_load_kw,
            "battery_soc_pct": state.battery.soc_pct,
            "active_alerts_count": len(state.active_alerts),
        }

    def _explain_runway(self, state: EnergyState) -> dict[str, Any]:
        """Generate storage runway explanation."""
        b = state.battery
        h = state.hydrogen
        if b.runway_hours is not None:
            runway_str = f"{b.runway_hours:.2f} hours under current deficit"
        elif state.net_power_kw >= 0:
            runway_str = "Infinite (generation currently covers all load; battery is charging or floating)"
        else:
            runway_str = "0.0 hours (battery exhausted)"

        answer = (
            f"Storage Runway Analysis for '{state.station_id}': "
            f"Battery SOC is {b.soc_pct:.1f}% with {b.usable_energy_kwh:.1f} kWh usable energy above reserve. "
            f"Estimated battery runway: {runway_str}. "
            f"Hydrogen storage is at {h.level_pct:.1f}% with {h.usable_energy_kwh:.1f} kWh available fuel cell energy."
        )
        return {
            "station_id": state.station_id,
            "answer": answer,
            "intent": "RUNWAY",
            "battery_soc_pct": b.soc_pct,
            "battery_runway_hours": b.runway_hours,
            "battery_usable_energy_kwh": b.usable_energy_kwh,
            "hydrogen_level_pct": h.level_pct,
            "hydrogen_usable_energy_kwh": h.usable_energy_kwh,
        }

    def _explain_alerts(self, state: EnergyState) -> dict[str, Any]:
        """Generate operational alerts explanation."""
        if not state.active_alerts:
            answer = f"No active operational alerts or telemetry anomalies for station '{state.station_id}'. All systems nominal."
        else:
            alerts_list = ", ".join(state.active_alerts)
            answer = (
                f"Station '{state.station_id}' has {len(state.active_alerts)} active alert(s): {alerts_list}. "
                f"Data quality is {state.data_quality.value}."
            )
        return {
            "station_id": state.station_id,
            "answer": answer,
            "intent": "ALERTS",
            "active_alerts": state.active_alerts,
            "data_quality": state.data_quality.value,
        }

    def _explain_generation(self, state: EnergyState) -> dict[str, Any]:
        """Generate generation breakdown explanation."""
        g = state.generation
        answer = (
            f"Renewable generation total: {g.total_generation_kw:.1f} kW. "
            f"Solar array contributes {g.solar_kw:.1f} kW ({g.solar_pct:.1f}%), "
            f"Wind turbines contribute {g.wind_kw:.1f} kW ({g.wind_pct:.1f}%)."
        )
        return {
            "station_id": state.station_id,
            "answer": answer,
            "intent": "GENERATION",
            "total_generation_kw": g.total_generation_kw,
            "solar_kw": g.solar_kw,
            "wind_kw": g.wind_kw,
            "solar_pct": g.solar_pct,
            "wind_pct": g.wind_pct,
        }

    def _explain_load(self, state: EnergyState) -> dict[str, Any]:
        """Generate load breakdown explanation."""
        l = state.load
        answer = (
            f"Total station load: {l.total_load_kw:.1f} kW. "
            f"Breakdown: Life support/P0: {l.critical_kw:.1f} kW, "
            f"Operational/P2: {l.operational_kw:.1f} kW, "
            f"Flexible/P3: {l.flexible_kw:.1f} kW, "
            f"Deferrable/P4: {l.deferrable_kw:.1f} kW."
        )
        return {
            "station_id": state.station_id,
            "answer": answer,
            "intent": "LOAD",
            "total_load_kw": l.total_load_kw,
            "critical_kw": l.critical_kw,
            "operational_kw": l.operational_kw,
            "flexible_kw": l.flexible_kw,
            "deferrable_kw": l.deferrable_kw,
        }
