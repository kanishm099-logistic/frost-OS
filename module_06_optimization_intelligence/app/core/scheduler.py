"""
Scheduler & Time Grid Engine.

Handles decision horizons (1h to 72h) and time step resolutions (5m to 1h).
Distinguishes real-time fast dispatch from strategic long-horizon planning.
"""

from __future__ import annotations

from typing import Tuple
from pydantic import BaseModel


class TimeGrid(BaseModel):
    """Grid parameters representing discrete time steps in optimization."""
    horizon_minutes: int
    time_step_minutes: int
    num_steps: int
    step_duration_hours: float


class SchedulerEngine:
    """Manages horizon configurations and classification of optimization runs."""

    @staticmethod
    def create_time_grid(horizon_minutes: int, time_step_minutes: int) -> TimeGrid:
        """Create validated TimeGrid structure."""
        horizon_minutes = max(60, min(4320, horizon_minutes))  # 1h to 72h bounds
        time_step_minutes = max(5, min(60, time_step_minutes))  # 5m to 1h bounds

        num_steps = max(1, horizon_minutes // time_step_minutes)
        step_duration_hours = time_step_minutes / 60.0

        return TimeGrid(
            horizon_minutes=horizon_minutes,
            time_step_minutes=time_step_minutes,
            num_steps=num_steps,
            step_duration_hours=step_duration_hours,
        )

    @staticmethod
    def classify_run_type(horizon_minutes: int) -> str:
        """Classify run as FAST (real-time), MEDIUM (dispatch), or SLOW (strategic)."""
        if horizon_minutes <= 60:
            return "FAST"      # 5–15min dispatch / 1h horizon
        elif horizon_minutes <= 360:
            return "MEDIUM"    # 1–6h dispatch
        else:
            return "SLOW"      # 24–72h strategic planning
