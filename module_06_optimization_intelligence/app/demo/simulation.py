"""
Polar Station Simulation & Scenario Benchmark Runner.

Demonstrates complete 72-hour mathematical energy optimization for a polar research station.
Evaluates BASELINE, LOW_RENEWABLE, and HIGH_LOAD scenarios.
Prints mission allocations, storage trajectories, M07 reserve compliance, and objective breakdowns.
"""

from __future__ import annotations

import sys
import uuid
from typing import Dict

from app.config.settings import get_settings
from app.models.optimization_request import (
    OptimizationRequest,
    ScenarioType,
    OptimizationMode,
)
from app.agents.optimizer_agent import OptimizerAgent
from app.clients.module_clients import MockSubsystemClients


def run_demo_simulation():
    """Execute complete 72-hour polar station optimization demo."""
    print("=" * 80)
    print("❄️ FROST OS — MODULE 06: OPTIMIZATION INTELLIGENCE DEMO SIMULATION ❄️")
    print("=" * 80)

    settings = get_settings()
    agent = OptimizerAgent(settings)

    # Build 72-hour (4320 minutes) optimization request
    horizon_mins = 4320  # 72 hours
    time_step_mins = 60  # 1 hour steps
    n_steps = horizon_mins // time_step_mins

    missions = MockSubsystemClients.get_mock_missions()
    energy_state = MockSubsystemClients.get_mock_energy_state()
    forecast = MockSubsystemClients.get_mock_forecast(n_steps, "BASELINE")
    equipment = MockSubsystemClients.get_mock_equipment()
    reserve = MockSubsystemClients.get_mock_reserve()

    request = OptimizationRequest(
        request_id=f"DEMO-SIM-{uuid.uuid4().hex[:6].upper()}",
        station_id="POLAR-STATION-ALPHA",
        horizon_minutes=horizon_mins,
        time_step_minutes=time_step_mins,
        mode=OptimizationMode.DETERMINISTIC,
        scenario=ScenarioType.BASELINE,
        missions=missions,
        energy_state=energy_state,
        forecast=forecast,
        equipment=equipment,
        reserve=reserve,
    )

    print(f"\n[1] Running Multi-Scenario Analysis over {horizon_mins//60}h Horizon ({n_steps} Time Steps)...")
    eval_out = agent.evaluate_and_optimize(request, run_multi_scenarios=True)

    base_res = eval_out["result"]
    scenarios_res: Dict[str, Any] = eval_out["scenario_results"]

    print("\n" + "=" * 80)
    print("📊 BASELINE SCENARIO RESULTS SUMMARY")
    print("=" * 80)
    print(f"Optimization ID    : {base_res.optimization_id}")
    print(f"Solver Status      : {base_res.solver_status}")
    print(f"Feasible           : {base_res.feasible}")
    print(f"Validation Passed  : {base_res.validation_passed}")
    print(f"Objective Value    : {base_res.objective_value}")
    print(f"Solve Duration     : {base_res.solve_time_seconds}s")

    print("\n--- Objective Term Breakdown ---")
    for term, val in base_res.objective_breakdown.items():
        print(f"  • {term:30s}: {val:10.2f}")

    print("\n--- Mission Allocations (Sample First 6 Hours) ---")
    for m_id in {a.mission_id for a in base_res.mission_allocations}:
        allocs = [a for a in base_res.mission_allocations if a.mission_id == m_id][:6]
        print(f"\n  Mission [{m_id}] Priority {allocs[0].priority}:")
        for a in allocs:
            print(f"    Step t={a.time_step:02d} ({a.time_minutes//60:02d}h): Allocated Power = {a.allocated_power_kw:6.2f} kW | Active = {a.is_active}")

    print("\n--- Storage Trajectories (Sample First 6 Hours) ---")
    for s in base_res.storage_schedule[:6]:
        print(f"  Step t={s.time_step:02d} ({s.time_minutes//60:02d}h): BESS SOC = {s.battery_soc*100:5.1f}% ({s.battery_energy_kwh:6.1f} kWh) | H2 Reserve = {s.hydrogen_energy_kwh:6.1f} kWh")

    print("\n--- M07 Reserve Trajectories (Sample First 6 Hours) ---")
    for r in base_res.reserve_trajectory[:6]:
        print(f"  Step t={r.time_step:02d}: Total Stored = {r.projected_stored_energy_kwh:6.1f} kWh | Required Reserve = {r.required_reserve_kwh:6.1f} kWh | Margin = {r.margin_kwh:6.1f} kWh | Met = {r.reserve_met}")

    print("\n" + "=" * 80)
    print("⚡ MULTI-SCENARIO RESILIENCE COMPARISON")
    print("=" * 80)
    for sc_name, sc_r in scenarios_res.items():
        status_symbol = "✅ FEASIBLE" if sc_r.feasible else "❌ INFEASIBLE"
        print(f"  • Scenario [{sc_name:20s}]: {status_symbol} | Objective = {sc_r.objective_value:10.2f}")

    print("\n🤖 AGENT EXECUTIVE RATIONALE:")
    print(eval_out["agent_explanation"])
    print("\n" + "=" * 80)
    print("Simulation completed successfully.")


if __name__ == "__main__":
    run_demo_simulation()
