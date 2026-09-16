"""
Frost OS Module 03 — Load Analyzer.

Classifies and aggregates observed station electrical demand into
critical (P0/P1), operational (P2), flexible (P3), and deferrable (P4) categories.
"""

from __future__ import annotations

from typing import Any
from app.models.energy_state import LoadBreakdown


class LoadAnalyzer:
    """Aggregates and categorizes instantaneous load telemetry."""

    @staticmethod
    def categorize_loads(
        device_loads: dict[str, tuple[float, str]],  # device_id -> (kw, priority_category)
    ) -> LoadBreakdown:
        """
        Aggregate observed device loads into priority tiers:
          critical: P0 / P1 / life-support / safety
          operational: P2 / lab / science equipment
          flexible: P3 / computing / HVAC
          deferrable: P4 / recreation / convenience
        """
        critical = 0.0
        operational = 0.0
        flexible = 0.0
        deferrable = 0.0

        for device_id, (kw, category) in device_loads.items():
            cat = category.upper()
            if cat in ("P0", "P1", "CRITICAL", "LIFE_SUPPORT", "SAFETY"):
                critical += kw
            elif cat in ("P2", "OPERATIONAL", "LABORATORY"):
                operational += kw
            elif cat in ("P3", "FLEXIBLE", "COMPUTING"):
                flexible += kw
            elif cat in ("P4", "DEFERRABLE", "RECREATION"):
                deferrable += kw
            else:
                operational += kw

        total = critical + operational + flexible + deferrable

        return LoadBreakdown(
            critical=round(critical, 2),
            operational=round(operational, 2),
            flexible=round(flexible, 2),
            deferrable=round(deferrable, 2),
            total=round(total, 2),
        )

    @classmethod
    def analyze_loads(
        cls,
        load_telemetry: list[dict[str, Any]] | dict[str, tuple[float, str]],
    ) -> LoadBreakdown:
        """Convenience method accepting list of load dicts or mapping."""
        if isinstance(load_telemetry, dict):
            return cls.categorize_loads(load_telemetry)

        device_loads: dict[str, tuple[float, str]] = {}
        for idx, item in enumerate(load_telemetry):
            dev_id = str(item.get("device_id", f"load_{idx}"))
            kw = float(item.get("power_kw", item.get("value", item.get("kw", 0.0))))
            prio = str(item.get("priority", item.get("tier", "P2")))
            device_loads[dev_id] = (kw, prio)

        return cls.categorize_loads(device_loads)
