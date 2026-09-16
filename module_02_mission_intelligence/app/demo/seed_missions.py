"""
Frost OS Module 02 — Polar Station Missions Demo & Seed Data.

Initializes realistic polar station workloads (P0 through P4), runs
deterministic enrichment, checks dependency constraints, demonstrates safety
rejection of sub-minimum power allocations, generates Module 06 profiles,
and executes Module 01 impact assessment.

Usage:
    python -m app.demo.seed_missions
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone

# Reconfigure stdout/stderr on Windows for Unicode support
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import structlog
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.mission_agent import MissionAgent
from app.config.settings import Settings
from app.core.mission_engine import MissionEngine
from app.events.event_types import MissionEventType
from app.events.publisher import MissionEventPublisher
from app.models.mission import (
    Base,
    Flexibility,
    Mission,
    MissionState,
    MissionType,
)
from app.models.priority import PriorityLevel
from app.storage.repository import MissionRepository

# Configure structlog
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


async def run_demo():
    """Execute the polar station mission intelligence demo."""
    print("\n" + "=" * 75)
    print("❄️  FROST OS — Module 02: Mission Intelligence Operational Demo")
    print("=" * 75 + "\n")

    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        mock_mode=True,
        station_id="FROST-STATION-ALPHA",
    )

    # 1. Initialize In-Memory Database
    engine_db = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine_db.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine_db, class_=AsyncSession, expire_on_commit=False)

    # 2. Initialize Services
    publisher = MissionEventPublisher(redis_client=None, stream_name=settings.stream_missions)
    engine = MissionEngine(settings)
    agent = MissionAgent(engine)

    now = datetime.now(timezone.utc)

    # 3. Define 6 Realistic Polar Workloads
    print("📋 Step 1: Initializing Polar Station Mission Workloads (P0 - P4)...")

    raw_missions = [
        # Mission 1: P0 Life Support
        Mission(
            mission_id="MSN-P0-LIFE",
            station_id=settings.station_id,
            name="Habitat Environmental & Life Support (ECLS)",
            description="Continuous cabin atmospheric pressure, oxygen circulation, and trace contaminant scrubbing",
            type=MissionType.LIFE_SUPPORT,
            priority=PriorityLevel.P0,
            required_power_kw=45.0,
            min_power_kw=35.0,
            max_power_kw=60.0,
            expected_duration_minutes=1440,  # 24h
            deadline=now + timedelta(hours=24),
            flexibility=Flexibility.INFLEXIBLE,
            status=MissionState.RUNNING,
        ),
        # Mission 2: P1 Ice Core Analysis (From Realistic Example)
        Mission(
            mission_id="MSN-P1-ICECOR",
            station_id=settings.station_id,
            name="Ice Core Cryogenic Spectrometry",
            description="Deep ice core layer spectrometry for paleoclimate atmospheric gas composition",
            type=MissionType.RESEARCH,
            priority=PriorityLevel.P1,
            required_power_kw=120.0,
            min_power_kw=90.0,
            max_power_kw=150.0,
            expected_duration_minutes=240,  # 4 hours
            deadline=now + timedelta(hours=18),
            flexibility=Flexibility.PARTIALLY_FLEXIBLE,
            status=MissionState.READY,
        ),
        # Mission 3: P1 Weather Monitoring
        Mission(
            mission_id="MSN-P1-WEATHR",
            station_id=settings.station_id,
            name="Blizzard Early Warning Doppler Radar",
            description="High-frequency polar radar tracking katabatic storm fronts and wind velocity",
            type=MissionType.WEATHER_MONITORING,
            priority=PriorityLevel.P1,
            required_power_kw=25.0,
            min_power_kw=18.0,
            max_power_kw=35.0,
            expected_duration_minutes=720,  # 12 hours
            deadline=now + timedelta(hours=14),
            flexibility=Flexibility.PARTIALLY_FLEXIBLE,
            status=MissionState.RUNNING,
        ),
        # Mission 4: P2 Laboratory Analysis (Depends on Mission 3)
        Mission(
            mission_id="MSN-P2-LABCEN",
            station_id=settings.station_id,
            name="Geomagnetic Core Sample Centrifuge",
            description="High-speed spin separation of geological particulates from glacial runoff",
            type=MissionType.LABORATORY,
            priority=PriorityLevel.P2,
            required_power_kw=20.0,
            min_power_kw=12.0,
            max_power_kw=28.0,
            expected_duration_minutes=180,  # 3 hours
            deadline=now + timedelta(hours=20),
            flexibility=Flexibility.FLEXIBLE,
            dependencies=["MSN-P1-WEATHR"],  # Depends on weather radar
            status=MissionState.SCHEDULED,
        ),
        # Mission 5: P3 Computing Workload (Shiftable within 12h window)
        Mission(
            mission_id="MSN-P3-CLIMAT",
            station_id=settings.station_id,
            name="Polar Climate Ensemble Simulation",
            description="Coupled atmospheric-ocean-ice grid compute simulation batch job",
            type=MissionType.COMPUTING,
            priority=PriorityLevel.P3,
            required_power_kw=100.0,
            min_power_kw=60.0,
            max_power_kw=120.0,
            expected_duration_minutes=180,  # 3 hours
            deadline=now + timedelta(hours=12),
            flexibility=Flexibility.FLEXIBLE,
            status=MissionState.READY,
        ),
        # Mission 6: P4 Recreation
        Mission(
            mission_id="MSN-P4-RECREA",
            station_id=settings.station_id,
            name="Crew Quarters Entertainment & Gym Media",
            description="Recreational media servers, lighting, and fitness equipment consoles",
            type=MissionType.RECREATION,
            priority=PriorityLevel.P4,
            required_power_kw=8.0,
            min_power_kw=2.0,
            max_power_kw=12.0,
            expected_duration_minutes=240,  # 4 hours
            deadline=now + timedelta(hours=8),
            flexibility=Flexibility.DEFERRABLE,
            status=MissionState.RUNNING,
        ),
    ]

    # 4. Enrich, Persist, and Publish Events
    async with session_factory() as session:
        repo = MissionRepository(session)
        for m in raw_missions:
            enriched = engine.enrich_mission(m)
            await repo.save(enriched)
            await publisher.publish_lifecycle(
                event_type=MissionEventType.MISSION_CREATED,
                station_id=enriched.station_id,
                mission_id=enriched.mission_id,
                correlation_id=f"demo-{enriched.mission_id}",
                payload={"name": enriched.name, "priority": enriched.priority.value},
            )
            print(f"   [+] Seeded {enriched.priority.value} Workload: {enriched.name}")
            print(f"       Power: {enriched.required_power_kw} kW (Min: {enriched.min_power_kw} kW, Max: {enriched.max_power_kw} kW)")
            print(f"       Energy: {enriched.energy_required_kwh} kWh + Buffer: {enriched.buffer_kwh} kWh = {enriched.protected_energy_kwh} kWh Protected")

    # 5. Verify Realistic Example Assertions (Ice Core Analysis)
    print("\n🔍 Step 2: Validating 'Ice Core Analysis' Calculations...")
    ice_core = raw_missions[1]
    expected_base_energy = 120.0 * 4.0  # 480 kWh
    expected_buffer = 480.0 * 0.30       # 144 kWh (+30% P1 buffer)
    expected_protected = 480.0 + 144.0   # 624 kWh

    assert ice_core.energy_required_kwh == expected_base_energy, f"Base energy should be {expected_base_energy}"
    assert ice_core.buffer_kwh == expected_buffer, f"Buffer should be {expected_buffer}"
    assert ice_core.protected_energy_kwh == expected_protected, f"Protected energy should be {expected_protected}"
    print(f"   ✓ Base Energy:     {ice_core.energy_required_kwh:.1f} kWh (Matches expected 480.0 kWh)")
    print(f"   ✓ P1 Buffer:       {ice_core.buffer_kwh:.1f} kWh (+30% margin = 144.0 kWh)")
    print(f"   ✓ Total Protected: {ice_core.protected_energy_kwh:.1f} kWh (Matches expected 624.0 kWh)")

    # 6. Verify Minimum Power Safety Constraint Enforcement
    print("\n🛡️  Step 3: Demonstrating Minimum Safe Power Enforcement...")
    print(f"   Testing proposed allocation of 70 kW for '{ice_core.name}' (min_power_kw = 90 kW)...")
    valid, safety_msg = engine.energy_estimator.validate_power_allocation(ice_core, proposed_kw=70.0)
    assert not valid, "Allocation below min_power_kw MUST be rejected!"
    print(f"   [REJECTED AS EXPECTED]: {safety_msg}")

    valid_ok, ok_msg = engine.energy_estimator.validate_power_allocation(ice_core, proposed_kw=90.0)
    assert valid_ok, "Allocation at min_power_kw must be accepted!"
    print(f"   [ACCEPTED AT BOUNDARY]: {ok_msg}")

    # 7. Test Prerequisite Dependency Enforcement
    print("\n🔗 Step 4: Testing Prerequisite Dependency Checks...")
    all_map = {m.mission_id: m for m in raw_missions}
    lab_mission = raw_missions[3]  # Depends on MSN-P1-WEATHR which is currently RUNNING (not COMPLETED)
    satisfied, unmet = engine.check_dependencies(lab_mission, all_map)
    print(f"   Mission '{lab_mission.name}' depends on: {lab_mission.dependencies}")
    print(f"   Dependency check: Satisfied = {satisfied}, Unmet = {unmet}")
    assert not satisfied, "Dependency must NOT be satisfied while prerequisite is RUNNING"
    can_start, start_msg = engine.validate_transition(lab_mission, MissionState.RUNNING, all_map)
    assert not can_start, "Transition to RUNNING must fail if dependency is incomplete"
    print(f"   [TRANSITION BLOCKED]: {start_msg}")

    # 8. Generate Structured Mission Profiles for Module 06 Optimizer
    print("\n⚡ Step 5: Generating Structured MissionProfiles for Module 06 Optimizer...")
    profiles = [engine.create_profile(m) for m in raw_missions]
    profiles.sort(key=lambda p: p.scheduling_score, reverse=True)

    print(f"{'Priority':<10} | {'Name':<35} | {'Score':<6} | {'Nominal kW':<10} | {'Min kW':<8} | {'Protected kWh':<13} | {'Flexibility'}")
    print("-" * 115)
    for p in profiles:
        print(
            f"{p.priority.value:<10} | {p.name[:35]:<35} | {p.scheduling_score:<6.1f} | "
            f"{p.required_power_kw:<10.1f} | {p.min_power_kw:<8.1f} | {p.protected_energy_kwh:<13.1f} | {p.flexibility.value}"
        )

    # 9. Simulate Module 01 Impact Analysis (Wind Drop 250 kW -> 90 kW)
    print("\n🌪️  Step 6: Simulating Module 01 Wind Drop Impact Analysis...")
    active_missions = [m for m in raw_missions if m.status in (MissionState.RUNNING, MissionState.READY)]
    impact = engine.assess_generation_impact(
        active_missions=active_missions,
        station_id=settings.station_id,
        current_generation_kw=90.0,
        baseline_generation_kw=250.0,
    )

    print(f"   Total Active Missions: {impact['total_active_missions']}")
    print(f"   Total Active Demand:   {impact['total_demand_kw']} kW")
    print(f"   Available Generation:  {impact['current_generation_kw']} kW")
    print(f"   Energy Deficit:        {impact['deficit_kw']} kW")
    print(f"   Critical Floor (P0+P1):{impact['critical_floor_kw']} kW")
    print("   Module 02 Recommendations for Orchestrator:")
    for rec in impact["recommendations"]:
        print(f"     -> {rec}")

    # 10. Agent Explanation Demonstration
    print("\n🤖 Step 7: Mission Agent Rationale Inspection...")
    explanation = agent.explain_mission_profile(profiles[0])
    print(f"   Agent rationale for #{profiles[0].priority.value} '{profiles[0].name}':")
    print(f"   '{explanation['agent_rationale']}'")

    print("\n" + "=" * 75)
    print("✅ DEMO COMPLETE — All assertions and constraints successfully verified!")
    print("❄️  Frost OS Module 02: Mission Intelligence is operational.")
    print("=" * 75 + "\n")

    await engine_db.dispose()


def main():
    """CLI entrypoint."""
    asyncio.run(run_demo())


if __name__ == "__main__":
    main()
