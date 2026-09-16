"""
Frost OS Module 04 — Energy Risk & Shortage Engine Tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.risk_engine import RiskEngine
from app.models.forecast import ForecastRecord, ForecastTarget
from app.models.risk import RiskLevel, RiskType


def test_wind_collapse_risk_detection():
    """Verify RiskEngine flags WIND_COLLAPSE_RISK when wind drops sharply."""
    risk_engine = RiskEngine()
    now = datetime.now(timezone.utc)

    # Initial high wind (55 kW) decaying to 5 kW at hour 6
    records = [
        ForecastRecord(
            station_id="station-alpha",
            created_at=now,
            horizon_minutes=60,
            target=ForecastTarget.WIND_GENERATION_KW,
            timestamp=now + timedelta(hours=1),
            prediction=55.0,
            lower_bound=45.0,
            upper_bound=65.0,
        ),
        ForecastRecord(
            station_id="station-alpha",
            created_at=now,
            horizon_minutes=360,
            target=ForecastTarget.WIND_GENERATION_KW,
            timestamp=now + timedelta(hours=6),
            prediction=6.0,
            lower_bound=0.0,
            upper_bound=12.0,
        ),
    ]

    risks, shortage = risk_engine.evaluate_risks("station-alpha", records)
    wind_risks = [r for r in risks if r.risk_type == RiskType.WIND_COLLAPSE_RISK]
    assert len(wind_risks) == 1
    assert wind_risks[0].risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL]
    assert wind_risks[0].probability >= 0.70


def test_battery_low_and_energy_deficit_risk():
    """Verify BATTERY_LOW_RISK and shortage assessment on severe deficit."""
    risk_engine = RiskEngine(battery_min_soc_pct=15.0)
    now = datetime.now(timezone.utc)

    records = [
        # SOC dropping to 12% (below 15% reserve)
        ForecastRecord(
            station_id="station-alpha",
            created_at=now,
            horizon_minutes=180,
            target=ForecastTarget.BATTERY_SOC_PCT,
            timestamp=now + timedelta(hours=3),
            prediction=12.0,
            lower_bound=8.0,
            upper_bound=16.0,
            unit="%",
        ),
        # Severe net power deficit (-45 kW)
        ForecastRecord(
            station_id="station-alpha",
            created_at=now,
            horizon_minutes=180,
            target=ForecastTarget.ENERGY_SURPLUS_DEFICIT_KW,
            timestamp=now + timedelta(hours=3),
            prediction=-45.0,
            lower_bound=-60.0,
            upper_bound=-30.0,
            unit="kW",
        ),
    ]

    risks, shortage = risk_engine.evaluate_risks(
        "station-alpha", records, current_battery_soc_pct=25.0
    )
    batt_risks = [r for r in risks if r.risk_type == RiskType.BATTERY_LOW_RISK]
    assert len(batt_risks) == 1
    assert batt_risks[0].risk_level == RiskLevel.CRITICAL

    assert shortage.expected_shortage_kwh > 0
    assert shortage.worst_case_shortage_kwh > shortage.expected_shortage_kwh
