"""
Frost OS Module 04 — Master Forecast Engine.

Orchestrates multi-target, multi-horizon forecast generation:
- 10 targets: solar, wind, total renewable, load, battery SOC/energy, hydrogen, net surplus/deficit, shortage risk, renewable availability
- 8 horizons: 5m, 15m, 30m, 1h, 6h, 24h, 48h, 72h
- Storage passive and scenario dispatch projections
- Enforces strict physical consistency and anti-leakage guards.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
import structlog

from app.core.feature_engineering import FeatureEngineer
from app.core.model_manager import ModelManager
from app.core.uncertainty import UncertaintyEstimator
from app.models.forecast import (
    DataQuality,
    ForecastRecord,
    ForecastRun,
    ForecastTarget,
)
from app.models.weather import NWPForecastRecord

logger = structlog.get_logger(__name__)


class ForecastEngine:
    """Master pipeline for polar research station predictive intelligence."""

    def __init__(
        self,
        station_id: str = "polar-station-alpha",
        solar_capacity_kw: float = 80.0,
        wind_capacity_kw: float = 120.0,
        battery_capacity_kwh: float = 500.0,
        hydrogen_capacity_kwh: float = 2500.0,
        base_load_kw: float = 35.0,
        latitude: float = -75.58,
        longitude: float = -26.66,
    ) -> None:
        self.station_id = station_id
        self.solar_capacity_kw = solar_capacity_kw
        self.wind_capacity_kw = wind_capacity_kw
        self.battery_capacity_kwh = battery_capacity_kwh
        self.hydrogen_capacity_kwh = hydrogen_capacity_kwh
        self.base_load_kw = base_load_kw

        self.feature_engineer = FeatureEngineer(
            station_id=station_id,
            latitude=latitude,
            longitude=longitude,
        )
        self.model_manager = ModelManager(
            solar_capacity_kw=solar_capacity_kw,
            wind_capacity_kw=wind_capacity_kw,
            base_load_kw=base_load_kw,
        )
        self.uncertainty_estimator = UncertaintyEstimator()

    def generate_forecast(
        self,
        nwp_records: list[NWPForecastRecord],
        history_df: pd.DataFrame,
        current_energy_state: dict[str, Any] | None = None,
        active_missions: list[dict[str, Any]] | None = None,
        equipment_health: dict[str, Any] | None = None,
        creation_time: datetime | None = None,
        horizon_hours: int = 72,
        data_quality: DataQuality = DataQuality.GOOD,
    ) -> ForecastRun:
        """
        Execute comprehensive forecast pipeline across 10 targets and all lead times up to horizon_hours.
        """
        now = creation_time or datetime.now(timezone.utc)
        records: list[ForecastRecord] = []

        # Current state values from M03
        state = current_energy_state or {}
        curr_soc = float(state.get("battery_soc_pct", state.get("battery", {}).get("soc_pct", 80.0)))
        curr_h2 = float(state.get("hydrogen_level_pct", state.get("hydrogen", {}).get("level_pct", 75.0)))

        # Turbine health from M05
        turbine_health = 1.0
        pv_health = 1.0
        if equipment_health:
            turbine_health = float(equipment_health.get("turbine_health_score", 1.0))
            pv_health = float(equipment_health.get("pv_health_score", 1.0))

        # Filter NWP records up to horizon_hours
        valid_nwp = [r for r in nwp_records if r.lead_time_hours <= horizon_hours]
        if not valid_nwp:
            logger.warning("no_valid_nwp_records_found_for_horizon", horizon_hours=horizon_hours)

        # Simulation state tracking for passive storage trajectory
        sim_battery_soc = curr_soc
        sim_h2_level = curr_h2
        prev_time = now

        for nwp in valid_nwp:
            v_time = nwp.valid_time
            lead_hrs = nwp.lead_time_hours
            lead_mins = int(lead_hrs * 60)
            dt_step_hrs = max(0.25, (v_time - prev_time).total_seconds() / 3600.0)
            prev_time = v_time

            # 1. Feature extraction with strict anti-leakage guarantee
            feats = self.feature_engineer.build_inference_features(
                creation_time=now,
                valid_time=v_time,
                history_df=history_df,
                nwp_temp_c=nwp.temperature_c,
                nwp_wind_ms=nwp.wind_speed_ms,
                nwp_cloud_pct=nwp.cloud_cover_pct,
                nwp_radiation_wm2=nwp.solar_radiation_wm2,
                active_missions=active_missions,
                equipment_health={"turbine_health_score": turbine_health, "pv_health_score": pv_health},
                storage_state={"battery_soc_pct": sim_battery_soc, "hydrogen_level_pct": sim_h2_level},
            )

            # 2. Solar Generation Point Prediction & Uncertainty
            solar_pt = self.model_manager.solar_model.predict(feats)
            solar_std = self.model_manager.get_residual_std(ForecastTarget.SOLAR_GENERATION_KW)
            solar_interval = self.uncertainty_estimator.estimate_interval(
                point_prediction=solar_pt,
                lead_time_hours=lead_hrs,
                base_residual_std=solar_std,
                data_quality=data_quality,
                physical_min=0.0,
                physical_max=self.solar_capacity_kw,
            )
            records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.SOLAR_GENERATION_KW,
                    timestamp=v_time,
                    prediction=solar_interval.prediction,
                    lower_bound=solar_interval.lower_bound,
                    upper_bound=solar_interval.upper_bound,
                    confidence=solar_interval.confidence,
                    unit="kW",
                    model_version=self.model_manager.solar_model.version,
                    data_quality=data_quality,
                )
            )

            # 3. Wind Generation Point Prediction & Uncertainty
            wind_pt = self.model_manager.wind_model.predict(feats)
            wind_std = self.model_manager.get_residual_std(ForecastTarget.WIND_GENERATION_KW)
            wind_interval = self.uncertainty_estimator.estimate_interval(
                point_prediction=wind_pt,
                lead_time_hours=lead_hrs,
                base_residual_std=wind_std,
                data_quality=data_quality,
                physical_min=0.0,
                physical_max=self.wind_capacity_kw * turbine_health,
            )
            records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.WIND_GENERATION_KW,
                    timestamp=v_time,
                    prediction=wind_interval.prediction,
                    lower_bound=wind_interval.lower_bound,
                    upper_bound=wind_interval.upper_bound,
                    confidence=wind_interval.confidence,
                    unit="kW",
                    model_version=self.model_manager.wind_model.version,
                    data_quality=data_quality,
                )
            )

            # 4. Total Renewable Generation
            total_ren_pt = round(solar_interval.prediction + wind_interval.prediction, 2)
            total_ren_lower = round(solar_interval.lower_bound + wind_interval.lower_bound, 2)
            total_ren_upper = round(solar_interval.upper_bound + wind_interval.upper_bound, 2)
            records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.TOTAL_RENEWABLE_GENERATION_KW,
                    timestamp=v_time,
                    prediction=total_ren_pt,
                    lower_bound=total_ren_lower,
                    upper_bound=total_ren_upper,
                    confidence=round((solar_interval.confidence + wind_interval.confidence) / 2.0, 3),
                    unit="kW",
                    model_version="hybrid_v0.1",
                    data_quality=data_quality,
                )
            )

            # 5. Station Load Prediction & Uncertainty
            load_pt = self.model_manager.load_model.predict(feats)
            load_std = self.model_manager.get_residual_std(ForecastTarget.STATION_LOAD_KW)
            load_interval = self.uncertainty_estimator.estimate_interval(
                point_prediction=load_pt,
                lead_time_hours=lead_hrs,
                base_residual_std=load_std,
                data_quality=data_quality,
                physical_min=15.0,
                physical_max=300.0,
            )
            records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.STATION_LOAD_KW,
                    timestamp=v_time,
                    prediction=load_interval.prediction,
                    lower_bound=load_interval.lower_bound,
                    upper_bound=load_interval.upper_bound,
                    confidence=load_interval.confidence,
                    unit="kW",
                    model_version=self.model_manager.load_model.version,
                    data_quality=data_quality,
                )
            )

            # 6. Energy Surplus / Deficit (kW)
            net_power_pt = round(total_ren_pt - load_interval.prediction, 2)
            net_lower = round(total_ren_lower - load_interval.upper_bound, 2)
            net_upper = round(total_ren_upper - load_interval.lower_bound, 2)
            records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.ENERGY_SURPLUS_DEFICIT_KW,
                    timestamp=v_time,
                    prediction=net_power_pt,
                    lower_bound=net_lower,
                    upper_bound=net_upper,
                    confidence=load_interval.confidence,
                    unit="kW",
                    model_version="balance_v0.1",
                    data_quality=data_quality,
                )
            )

            # 7. Passive Storage Trajectory Projection (Battery SOC, Energy, Hydrogen)
            if net_power_pt >= 0:
                # Excess generation charges battery (92% roundtrip eff)
                charge_energy_kwh = net_power_pt * dt_step_hrs * 0.92
                sim_battery_soc = min(95.0, sim_battery_soc + (charge_energy_kwh / self.battery_capacity_kwh) * 100.0)
            else:
                deficit_energy_kwh = abs(net_power_pt) * dt_step_hrs / 0.92
                usable_batt_kwh = max(0.0, (sim_battery_soc - 15.0) / 100.0 * self.battery_capacity_kwh)
                if deficit_energy_kwh <= usable_batt_kwh:
                    sim_battery_soc = max(15.0, sim_battery_soc - (deficit_energy_kwh / self.battery_capacity_kwh) * 100.0)
                else:
                    sim_battery_soc = 15.0
                    unmet_kwh = deficit_energy_kwh - usable_batt_kwh
                    # Discharging hydrogen fuel cell (55% efficiency)
                    h2_kwh = unmet_kwh / 0.55
                    sim_h2_level = max(10.0, sim_h2_level - (h2_kwh / self.hydrogen_capacity_kwh) * 100.0)

            # Battery SOC %
            soc_interval = self.uncertainty_estimator.estimate_interval(
                point_prediction=sim_battery_soc,
                lead_time_hours=lead_hrs,
                base_residual_std=2.0,
                data_quality=data_quality,
                physical_min=0.0,
                physical_max=100.0,
            )
            records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.BATTERY_SOC_PCT,
                    timestamp=v_time,
                    prediction=soc_interval.prediction,
                    lower_bound=soc_interval.lower_bound,
                    upper_bound=soc_interval.upper_bound,
                    confidence=soc_interval.confidence,
                    unit="%",
                    model_version="bess_passive_v0.1",
                    data_quality=data_quality,
                )
            )

            # Battery Stored Energy (kWh)
            batt_kwh_pt = round((sim_battery_soc / 100.0) * self.battery_capacity_kwh, 1)
            records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.BATTERY_ENERGY_KWH,
                    timestamp=v_time,
                    prediction=batt_kwh_pt,
                    lower_bound=round(soc_interval.lower_bound / 100.0 * self.battery_capacity_kwh, 1),
                    upper_bound=round(soc_interval.upper_bound / 100.0 * self.battery_capacity_kwh, 1),
                    confidence=soc_interval.confidence,
                    unit="kWh",
                    model_version="bess_passive_v0.1",
                    data_quality=data_quality,
                )
            )

            # Hydrogen Level %
            h2_interval = self.uncertainty_estimator.estimate_interval(
                point_prediction=sim_h2_level,
                lead_time_hours=lead_hrs,
                base_residual_std=1.2,
                data_quality=data_quality,
                physical_min=0.0,
                physical_max=100.0,
            )
            records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.HYDROGEN_LEVEL_PCT,
                    timestamp=v_time,
                    prediction=h2_interval.prediction,
                    lower_bound=h2_interval.lower_bound,
                    upper_bound=h2_interval.upper_bound,
                    confidence=h2_interval.confidence,
                    unit="%",
                    model_version="h2_passive_v0.1",
                    data_quality=data_quality,
                )
            )

            # 8. Renewable Availability Index (0.0 to 1.0)
            avail = 0.0
            if nwp.wind_speed_ms >= 3.0 and nwp.wind_speed_ms <= 25.0:
                avail += 0.5
            if feats["solar_elevation_deg"] > 0:
                avail += 0.5 * max(0.0, 1.0 - (nwp.cloud_cover_pct / 100.0))
            records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.RENEWABLE_AVAILABILITY,
                    timestamp=v_time,
                    prediction=round(avail, 2),
                    lower_bound=round(max(0.0, avail - 0.15), 2),
                    upper_bound=round(min(1.0, avail + 0.15), 2),
                    confidence=0.85,
                    unit="index",
                    model_version="availability_v0.1",
                    data_quality=data_quality,
                )
            )

            # 9. Shortage Risk Score (0.0 to 1.0)
            shortage_risk_score = 0.0
            if net_power_pt < 0:
                shortage_risk_score = min(1.0, abs(net_power_pt) / 80.0)
            if sim_battery_soc < 25.0:
                shortage_risk_score = min(1.0, shortage_risk_score + 0.4)
            records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.ENERGY_SHORTAGE_RISK,
                    timestamp=v_time,
                    prediction=round(shortage_risk_score, 2),
                    lower_bound=round(max(0.0, shortage_risk_score - 0.2), 2),
                    upper_bound=round(min(1.0, shortage_risk_score + 0.2), 2),
                    confidence=0.82,
                    unit="index",
                    model_version="risk_prob_v0.1",
                    data_quality=data_quality,
                )
            )

        run = ForecastRun(
            station_id=self.station_id,
            created_at=now,
            horizon_hours=horizon_hours,
            records=records,
            metadata={
                "nwp_count": len(valid_nwp),
                "data_quality": data_quality.value,
                "solar_installed_kw": self.solar_capacity_kw,
                "wind_installed_kw": self.wind_capacity_kw,
            },
        )
        return run
