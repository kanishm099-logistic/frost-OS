"""
Frost OS Module 04 — Forecast Agent Interpretation Layer Tests.
"""

from __future__ import annotations

from app.agents.forecast_agent import ForecastAgent


def test_agent_event_trigger_decisions():
    """Verify agent decides when to trigger on-demand forecast recalculations."""
    agent = ForecastAgent("polar-station-alpha")

    # Routine heartbeat
    routine = agent.evaluate_event_trigger("HEARTBEAT", {})
    assert routine["should_recalculate"] is False

    # Generation drop event
    gen_drop = agent.evaluate_event_trigger("WIND_DROP_ALERT", {"station_id": "polar-station-alpha"})
    assert gen_drop["should_recalculate"] is True
    assert gen_drop["priority"] == "HIGH"
    assert "15m" in gen_drop["horizons"]

    # Storm warning event
    storm = agent.evaluate_event_trigger("BLIZZARD_WARNING", {"station_id": "polar-station-alpha"})
    assert storm["should_recalculate"] is True
    assert storm["priority"] == "CRITICAL"
    assert "72h" in storm["horizons"]


def test_agent_answer_queries():
    """Verify conversational Q&A without hardware commanding."""
    agent = ForecastAgent("polar-station-alpha")

    context = {
        "trend": "declining",
        "lowest_generation_kw": 18.5,
        "recovery_expected_hour": 14,
        "expected_shortage_kwh": 120.0,
        "shortage_probability": 0.82,
    }

    # Query about wind recovery
    ans_wind = agent.answer_query("When will wind power recover?", context)
    assert "declining" in ans_wind
    assert "18.5" in ans_wind

    # Query about shortage
    ans_shortage = agent.answer_query("What is our projected energy shortage?", context)
    assert "120.0" in ans_shortage
    assert "82.0%" in ans_shortage
