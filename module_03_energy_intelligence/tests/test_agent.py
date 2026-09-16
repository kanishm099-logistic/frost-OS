"""
Frost OS Module 03 — Energy Agent Tests.
"""

from __future__ import annotations

import pytest

from app.agents.energy_agent import EnergyAgent
from app.core.energy_engine import EnergyEngine
from app.models.telemetry import TelemetryRecord


def test_agent_status_query(energy_engine: EnergyEngine, sample_telemetry_batch: list[TelemetryRecord]):
    """Verify agent answers general status queries."""
    energy_engine.process_telemetry_sync(sample_telemetry_batch)
    agent = EnergyAgent(energy_engine)

    res = agent.query("halley_vi", "What is the station's current energy state?")
    assert res["intent"] == "STATUS"
    assert "halley_vi" in res["answer"]
    assert "deficit" in res["answer"].lower() or "surplus" in res["answer"].lower()
    assert res["generation_kw"] == 300.0


def test_agent_runway_query(energy_engine: EnergyEngine, sample_telemetry_batch: list[TelemetryRecord]):
    """Verify agent answers battery runway queries."""
    energy_engine.process_telemetry_sync(sample_telemetry_batch)
    agent = EnergyAgent(energy_engine)

    res = agent.query("halley_vi", "How many hours of battery runway do we have remaining?")
    assert res["intent"] == "RUNWAY"
    assert res["battery_soc_pct"] == 72.0
    assert res["battery_runway_hours"] is not None
    assert "hours" in res["answer"]


def test_agent_what_if_feasible_load(energy_engine: EnergyEngine, sample_telemetry_batch: list[TelemetryRecord]):
    """Verify agent correctly identifies a feasible load addition."""
    energy_engine.process_telemetry_sync(sample_telemetry_batch)
    agent = EnergyAgent(energy_engine)

    # Adding 20 kW for 2 hours (needs 40 kWh; usable battery is > 200 kWh)
    res = agent.evaluate_load_addition("halley_vi", additional_kw=20.0, duration_hours=2.0)
    assert res["feasible"] is True
    assert res["verdict"] in ("FEASIBLE", "MARGINAL")
    assert res["additional_kw"] == 20.0


def test_agent_what_if_infeasible_load_exceeds_rating(energy_engine: EnergyEngine, sample_telemetry_batch: list[TelemetryRecord]):
    """Verify agent rejects loads that exceed max battery inverter discharge power."""
    energy_engine.process_telemetry_sync(sample_telemetry_batch)
    agent = EnergyAgent(energy_engine)

    # Adding 600 kW load exceeds 400 kW inverter max discharge limit
    res = agent.evaluate_load_addition("halley_vi", additional_kw=600.0, duration_hours=1.0)
    assert res["feasible"] is False
    assert res["verdict"] == "INFEASIBLE"
    assert "exceeds" in res["reason"]
