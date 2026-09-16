"""
Frost OS Module 01 — Wind Drop Simulation Demo.

Simulates a wind power drop from 180 kW to 70 kW and runs
the full orchestration pipeline with mock module clients.

Usage:
    python -m app.demo.simulate_wind_drop

This demo:
1. Injects a WIND_POWER_DROP event (180→70 kW)
2. Mock Forecast: continued wind decline over 24 hours
3. Mock Diagnostic: turbine icing risk detected
4. Mock Mission: 3 active workloads (P1 life-support, P2 comms, P3 data)
5. Mock Optimizer: proposed load shedding (reduce P3 by 40%, maintain P1/P2)
6. Mock Reserve: validates 48h minimum reserve maintained
7. Mock Safety: passes all constraints
8. Creates AWAITING_AUTHORIZATION action plan
9. After simulated YES → sends to mock M08
10. Verifies COMPLETED status
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import structlog

# Configure logging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("demo")


async def run_simulation():
    """Run the wind drop simulation."""
    from sqlalchemy import StaticPool
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.clients.diagnostic_client import MockDiagnosticClient
    from app.clients.energy_client import MockEnergyClient
    from app.clients.execution_client import MockExecutionClient
    from app.clients.forecast_client import MockForecastClient
    from app.clients.mission_client import MockMissionClient
    from app.clients.optimizer_client import MockOptimizerClient
    from app.clients.reserve_client import MockReserveClient
    from app.config.settings import Settings
    from app.core.decision_manager import DecisionManager
    from app.core.event_router import EventRouter
    from app.core.orchestrator import ModuleClients, Orchestrator
    from app.core.workflow_engine import WorkflowEngine, WorkflowRegistry
    from app.models.event import Base, EventType, Severity, StationEvent
    from app.storage.repository import (
        ActionPlanRepository,
        AuditRepository,
        DecisionRepository,
        EventRepository,
        WorkflowRunRepository,
    )
    from app.workflows.equipment_failure import equipment_failure_workflow
    from app.workflows.generation_drop import generation_drop_workflow
    from app.workflows.low_reserve import low_reserve_workflow
    from app.workflows.mission_start import mission_start_workflow
    from app.workflows.weather_risk import weather_risk_workflow

    print("\n" + "=" * 70)
    print("❄️  FROST OS — Module 01: Wind Drop Simulation Demo")
    print("=" * 70 + "\n")

    # ── Setup ─────────────────────────────────────────────────────────
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        mock_mode=True,
        station_id="FROST-STATION-ALPHA",
    )

    # In-memory database
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # Register workflows
    registry = WorkflowRegistry()
    registry.register("generation_drop", generation_drop_workflow)
    registry.register("mission_start", mission_start_workflow)
    registry.register("equipment_failure", equipment_failure_workflow)
    registry.register("low_reserve", low_reserve_workflow)
    registry.register("weather_risk", weather_risk_workflow)

    # Create components
    router = EventRouter()
    workflow_engine = WorkflowEngine(registry)
    decision_manager = DecisionManager(settings)
    clients = ModuleClients(
        energy=MockEnergyClient(settings),
        forecast=MockForecastClient(settings),
        diagnostic=MockDiagnosticClient(settings),
        mission=MockMissionClient(settings),
        optimizer=MockOptimizerClient(settings),
        reserve=MockReserveClient(settings),
        execution=MockExecutionClient(settings),
    )

    orchestrator = Orchestrator(
        settings=settings,
        router=router,
        workflow_engine=workflow_engine,
        decision_manager=decision_manager,
        clients=clients,
    )

    # ── Step 1: Create Wind Drop Event ────────────────────────────────
    print("📡 Step 1: Wind power drop detected")
    print("   Wind generation dropped from 180 kW to 70 kW (61.1% decline)")
    print()

    event = StationEvent(
        source="wind-sensor-array-01",
        event_type=EventType.WIND_POWER_DROP,
        severity=Severity.HIGH,
        station_id="FROST-STATION-ALPHA",
        payload={
            "previous_kw": 180.0,
            "current_kw": 70.0,
            "drop_pct": 61.1,
            "turbine_id": "WIND-TURBINE-01",
        },
    )

    # ── Step 2: Process through pipeline ──────────────────────────────
    print("⚙️  Step 2: Processing through orchestration pipeline...")
    print("   Pipeline: Event → Validate → Classify → Route → Gather → Analyze → Optimize → Safety → Plan")
    print()

    async with session_factory() as session:
        event_repo = EventRepository(session)
        decision_repo = DecisionRepository(session)
        plan_repo = ActionPlanRepository(session)
        audit_repo = AuditRepository(session)
        workflow_repo = WorkflowRunRepository(session)

        result = await orchestrator.process_event(
            event=event,
            event_repo=event_repo,
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
            workflow_repo=workflow_repo,
        )

        decision_id = result["decision_id"]
        plan_id = result["plan_id"]

        # ── Step 3: Display results ───────────────────────────────────
        print(f"✅ Step 3: Pipeline complete")
        print(f"   Decision ID: {decision_id}")
        print(f"   Plan ID:     {plan_id}")
        print(f"   Status:      {result['status']}")
        print(f"   Requires Authorization: {result.get('requires_authorization', False)}")
        print()

        # Display action plan details
        plan_record = await plan_repo.get_by_id(plan_id)
        if plan_record:
            print("📋 Action Plan Details:")
            print(f"   Reason: {plan_record.reason}")
            print(f"   Safety Status: {plan_record.safety_status.value}")
            print(f"   Projected Reserve: {plan_record.projected_reserve_kwh} kWh")
            print(f"   Required Reserve:  {plan_record.required_reserve_kwh} kWh")
            print(f"   Actions ({len(plan_record.actions)}):")
            for i, action in enumerate(plan_record.actions, 1):
                print(f"     {i}. [{action.get('action_type', '?')}] {action.get('target', '?')}")
                print(f"        {action.get('description', '')}")
            print()

        # Display state transitions
        transitions = await decision_repo.get_transitions(decision_id)
        print("📊 Decision State Transitions:")
        for t in transitions:
            print(f"   {t.from_status.value} → {t.to_status.value}")
            if t.reason:
                print(f"      Reason: {t.reason}")
        print()

        # ── Step 4: Authorize ─────────────────────────────────────────
        print("🔐 Step 4: Simulating human authorization...")
        print("   Operator 'Dr. Sarah Chen' reviews and approves the plan")
        print()

        auth_result = await orchestrator.authorize_plan(
            plan_id=plan_id,
            authorized_by="dr-sarah-chen",
            reason="Reviewed analysis and approved — proceed with load shedding and de-icing",
            decision_repo=decision_repo,
            plan_repo=plan_repo,
            audit_repo=audit_repo,
            event_repo=event_repo,
        )

        print(f"✅ Step 5: Plan authorized and executed")
        print(f"   Authorization: {auth_result['status']}")
        print(f"   Authorized by: {auth_result['authorized_by']}")
        if "execution" in auth_result:
            exec_data = auth_result["execution"]
            print(f"   Execution Status: {exec_data.get('status', '?')}")
            if "verification" in exec_data:
                verification = exec_data["verification"].get("verification", {})
                print(f"   All Actions Successful: {verification.get('all_actions_successful', '?')}")
                print(f"   Post-Execution Generation: {verification.get('post_execution_generation_kw', '?')} kW")
                print(f"   Post-Execution Demand: {verification.get('post_execution_demand_kw', '?')} kW")
        print()

        # ── Step 6: Verify final state ────────────────────────────────
        final_decision = await decision_repo.get_by_id(decision_id)
        final_plan = await plan_repo.get_by_id(plan_id)
        final_transitions = await decision_repo.get_transitions(decision_id)

        print("🏁 Step 6: Final State Verification")
        print(f"   Decision Status: {final_decision.status.value}")
        print(f"   Plan Status:     {final_plan.status.value}")
        print(f"   Total Transitions: {len(final_transitions)}")
        print()

        print("📊 Complete State Machine Trace:")
        for t in final_transitions:
            marker = "✓" if t.to_status.value == "COMPLETED" else "→"
            print(f"   {marker} {t.from_status.value} → {t.to_status.value}")
        print()

        # Verify
        assert final_decision.status.value == "COMPLETED", "Decision should be COMPLETED"
        assert final_plan.status.value == "COMPLETED", "Plan should be COMPLETED"

    print("=" * 70)
    print("✅ SIMULATION COMPLETE — All assertions passed!")
    print("❄️  Frost OS Module 01 Orchestrator is operational.")
    print("=" * 70 + "\n")

    # Cleanup
    await engine.dispose()


def main():
    """Entry point for the simulation."""
    asyncio.run(run_simulation())


if __name__ == "__main__":
    main()
