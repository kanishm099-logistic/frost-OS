"""
Frost OS Module 04 — Scenario Engine.

Generates the 9 operational what-if scenarios for Module 06 Optimization
and Module 07 Reserve/Safety:
1. BASELINE
2. LOW_RENEWABLE
3. HIGH_RENEWABLE
4. HIGH_LOAD
5. LOW_WIND
6. SOLAR_DROP
7. STORM
8. EQUIPMENT_DEGRADATION
9. COMMUNICATION_LOSS

Scenarios modify forecast environmental inputs and uncertainty bounds without directly commanding hardware.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.forecast import ForecastRecord, ForecastTarget, DataQuality
from app.models.scenario import ScenarioConfig, ScenarioResult, ScenarioType
from app.models.weather import NWPForecastRecord


class ScenarioEngine:
    """Evaluates multi-horizon forecast trajectories under 9 operational scenarios."""

    def __init__(
        self,
        station_id: str = "polar-station-alpha",
        solar_capacity_kw: float = 80.0,
        wind_capacity_kw: float = 120.0,
        battery_capacity_kwh: float = 500.0,
        hydrogen_capacity_kwh: float = 2500.0,
    ) -> None:
        self.station_id = station_id
        self.solar_capacity_kw = solar_capacity_kw
        self.wind_capacity_kw = wind_capacity_kw
        self.battery_capacity_kwh = battery_capacity_kwh
        self.hydrogen_capacity_kwh = hydrogen_capacity_kwh

    def get_default_configs(self) -> dict[ScenarioType, ScenarioConfig]:
        """Return canonical parameter configurations for all 9 scenarios."""
        return {
            ScenarioType.BASELINE: ScenarioConfig(
                scenario_type=ScenarioType.BASELINE,
                description="Nominal NWP and ML point forecast baseline",
            ),
            ScenarioType.LOW_RENEWABLE: ScenarioConfig(
                scenario_type=ScenarioType.LOW_RENEWABLE,
                wind_multiplier=0.60,
                solar_multiplier=0.35,
                cloud_cover_override=85.0,
                uncertainty_multiplier=1.4,
                description="10th percentile wind coupled with high cloud cover solar suppression",
            ),
            ScenarioType.HIGH_RENEWABLE: ScenarioConfig(
                scenario_type=ScenarioType.HIGH_RENEWABLE,
                wind_multiplier=1.25,
                solar_multiplier=1.15,
                cloud_cover_override=10.0,
                description="90th percentile wind and optimal clear-sky polar solar output",
            ),
            ScenarioType.HIGH_LOAD: ScenarioConfig(
                scenario_type=ScenarioType.HIGH_LOAD,
                load_multiplier=1.35,
                temperature_delta_c=-10.0,
                description="Severe polar cold wave causing +35% heating demand and concurrent mission operations",
            ),
            ScenarioType.LOW_WIND: ScenarioConfig(
                scenario_type=ScenarioType.LOW_WIND,
                wind_multiplier=0.15,
                wind_speed_override_ms=1.8,
                description="Stagnant polar high-pressure ridge below turbine cut-in speed (3 m/s)",
            ),
            ScenarioType.SOLAR_DROP: ScenarioConfig(
                scenario_type=ScenarioType.SOLAR_DROP,
                solar_multiplier=0.05,
                cloud_cover_override=98.0,
                description="Severe blizzard/fog causing 95%+ solar radiation collapse",
            ),
            ScenarioType.STORM: ScenarioConfig(
                scenario_type=ScenarioType.STORM,
                wind_speed_override_ms=28.5,  # Above cut-out (25 m/s)
                wind_multiplier=0.0,          # Turbine cut-out shutdown
                solar_multiplier=0.05,
                temperature_delta_c=-8.0,
                uncertainty_multiplier=2.0,
                description="Severe katabatic blizzard exceeding 25 m/s cut-out; all turbines feather to safety stop",
            ),
            ScenarioType.EQUIPMENT_DEGRADATION: ScenarioConfig(
                scenario_type=ScenarioType.EQUIPMENT_DEGRADATION,
                equipment_derating_factor=0.50,
                wind_multiplier=0.50,
                solar_multiplier=0.50,
                description="Subsystem degradation (blade icing + inverter failure) derating capacity by 50%",
            ),
            ScenarioType.COMMUNICATION_LOSS: ScenarioConfig(
                scenario_type=ScenarioType.COMMUNICATION_LOSS,
                uncertainty_multiplier=2.5,
                description="NWP satellite uplink severed; fallback persistence forecast with 2.5x widened intervals",
            ),
        }

    def generate_scenario(
        self,
        scenario_type: ScenarioType,
        base_records: list[ForecastRecord],
        custom_config: ScenarioConfig | None = None,
        initial_battery_soc_pct: float = 80.0,
        initial_hydrogen_pct: float = 75.0,
    ) -> ScenarioResult:
        """
        Evaluate forecast records under scenario assumptions and project storage depletion trajectory.
        """
        config = custom_config or self.get_default_configs()[scenario_type]
        now = datetime.now(timezone.utc)

        scenario_records: list[ForecastRecord] = []
        # Group by timestamp to compute net power and storage trajectory
        by_timestamp: dict[datetime, dict[ForecastTarget, ForecastRecord]] = {}
        for r in base_records:
            by_timestamp.setdefault(r.timestamp, {})[r.target] = r

        sorted_ts = sorted(by_timestamp.keys())
        soc = initial_battery_soc_pct
        h2 = initial_hydrogen_pct
        min_soc = soc
        min_h2 = h2
        total_shortage_kwh = 0.0
        worst_deficit_kw = 0.0

        prev_time = now

        for ts in sorted_ts:
            dt_hours = max(0.25, (ts - prev_time).total_seconds() / 3600.0)
            prev_time = ts

            targets = by_timestamp[ts]

            # Solar modification
            base_solar = targets.get(ForecastTarget.SOLAR_GENERATION_KW)
            if base_solar:
                scen_solar = round(
                    min(self.solar_capacity_kw, max(0.0, base_solar.prediction * config.solar_multiplier * config.equipment_derating_factor)),
                    2,
                )
                half_width = (base_solar.upper_bound - base_solar.lower_bound) / 2.0 * config.uncertainty_multiplier
                scen_solar_rec = ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=base_solar.horizon_minutes,
                    target=ForecastTarget.SOLAR_GENERATION_KW,
                    timestamp=ts,
                    prediction=scen_solar,
                    lower_bound=max(0.0, round(scen_solar - half_width, 2)),
                    upper_bound=min(self.solar_capacity_kw, round(scen_solar + half_width, 2)),
                    confidence=max(0.1, round(base_solar.confidence / config.uncertainty_multiplier, 2)),
                    unit="kW",
                    model_version=f"{base_solar.model_version}-{scenario_type.value}",
                    data_quality=DataQuality.DEGRADED if config.uncertainty_multiplier > 1.5 else DataQuality.GOOD,
                )
                scenario_records.append(scen_solar_rec)
            else:
                scen_solar = 0.0

            # Wind modification
            base_wind = targets.get(ForecastTarget.WIND_GENERATION_KW)
            if base_wind:
                if scenario_type == ScenarioType.STORM or (config.wind_speed_override_ms and config.wind_speed_override_ms > 25.0):
                    scen_wind = 0.0  # Storm cut-out feathering
                elif config.wind_speed_override_ms and config.wind_speed_override_ms < 3.0:
                    scen_wind = 0.0  # Cut-in deficit
                else:
                    scen_wind = round(
                        min(self.wind_capacity_kw, max(0.0, base_wind.prediction * config.wind_multiplier * config.equipment_derating_factor)),
                        2,
                    )

                half_width = (base_wind.upper_bound - base_wind.lower_bound) / 2.0 * config.uncertainty_multiplier
                scen_wind_rec = ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=base_wind.horizon_minutes,
                    target=ForecastTarget.WIND_GENERATION_KW,
                    timestamp=ts,
                    prediction=scen_wind,
                    lower_bound=max(0.0, round(scen_wind - half_width, 2)),
                    upper_bound=min(self.wind_capacity_kw, round(scen_wind + half_width, 2)),
                    confidence=max(0.1, round(base_wind.confidence / config.uncertainty_multiplier, 2)),
                    unit="kW",
                    model_version=f"{base_wind.model_version}-{scenario_type.value}",
                    data_quality=DataQuality.DEGRADED if config.uncertainty_multiplier > 1.5 else DataQuality.GOOD,
                )
                scenario_records.append(scen_wind_rec)
            else:
                scen_wind = 0.0

            # Load modification
            base_load = targets.get(ForecastTarget.STATION_LOAD_KW)
            if base_load:
                scen_load = round(max(20.0, base_load.prediction * config.load_multiplier), 2)
                half_width = (base_load.upper_bound - base_load.lower_bound) / 2.0 * config.uncertainty_multiplier
                scen_load_rec = ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=base_load.horizon_minutes,
                    target=ForecastTarget.STATION_LOAD_KW,
                    timestamp=ts,
                    prediction=scen_load,
                    lower_bound=max(15.0, round(scen_load - half_width, 2)),
                    upper_bound=round(scen_load + half_width, 2),
                    confidence=max(0.1, round(base_load.confidence / config.uncertainty_multiplier, 2)),
                    unit="kW",
                    model_version=f"{base_load.model_version}-{scenario_type.value}",
                    data_quality=DataQuality.GOOD,
                )
                scenario_records.append(scen_load_rec)
            else:
                scen_load = 35.0

            # Total renewable generation
            total_ren = scen_solar + scen_wind
            lead_mins = base_load.horizon_minutes if base_load else int((ts - now).total_seconds() / 60)
            scenario_records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.TOTAL_RENEWABLE_GENERATION_KW,
                    timestamp=ts,
                    prediction=round(total_ren, 2),
                    lower_bound=round(max(0.0, total_ren * 0.8), 2),
                    upper_bound=round(total_ren * 1.2, 2),
                    confidence=0.80,
                    unit="kW",
                    model_version=f"total_ren-{scenario_type.value}",
                )
            )

            # Net power balance (+ surplus, - deficit)
            net_power = round(total_ren - scen_load, 2)
            scenario_records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.ENERGY_SURPLUS_DEFICIT_KW,
                    timestamp=ts,
                    prediction=net_power,
                    lower_bound=round(net_power - 12.0, 2),
                    upper_bound=round(net_power + 12.0, 2),
                    confidence=0.80,
                    unit="kW",
                    model_version=f"net_power-{scenario_type.value}",
                )
            )

            # Passive storage trajectory update
            if net_power >= 0:
                # Excess power charges battery (92% efficiency)
                charge_kwh = net_power * dt_hours * 0.92
                soc = min(95.0, soc + (charge_kwh / self.battery_capacity_kwh) * 100.0)
            else:
                deficit_kw = abs(net_power)
                worst_deficit_kw = max(worst_deficit_kw, deficit_kw)
                discharge_kwh = deficit_kw * dt_hours / 0.92

                # Deplete battery down to minimum reserve 15%
                usable_battery_kwh = max(0.0, (soc - 15.0) / 100.0 * self.battery_capacity_kwh)
                if discharge_kwh <= usable_battery_kwh:
                    soc = max(15.0, soc - (discharge_kwh / self.battery_capacity_kwh) * 100.0)
                else:
                    soc = 15.0
                    unmet_kwh = discharge_kwh - usable_battery_kwh
                    # Try hydrogen fuel cell buffer (55% efficiency)
                    usable_h2_kwh = max(0.0, (h2 - 10.0) / 100.0 * self.hydrogen_capacity_kwh * 0.55)
                    if unmet_kwh <= usable_h2_kwh:
                        h2_consumed = unmet_kwh / 0.55
                        h2 = max(10.0, h2 - (h2_consumed / self.hydrogen_capacity_kwh) * 100.0)
                    else:
                        h2 = 10.0
                        actual_shortage = unmet_kwh - usable_h2_kwh
                        total_shortage_kwh += actual_shortage

            min_soc = min(min_soc, soc)
            min_h2 = min(min_h2, h2)

            scenario_records.append(
                ForecastRecord(
                    station_id=self.station_id,
                    created_at=now,
                    horizon_minutes=lead_mins,
                    target=ForecastTarget.BATTERY_SOC_PCT,
                    timestamp=ts,
                    prediction=round(soc, 1),
                    lower_bound=round(max(0.0, soc - 4.0), 1),
                    upper_bound=round(min(100.0, soc + 4.0), 1),
                    confidence=0.82,
                    unit="%",
                    model_version=f"bess-{scenario_type.value}",
                )
            )

        return ScenarioResult(
            station_id=self.station_id,
            scenario_type=scenario_type,
            created_at=now,
            description=config.description,
            records=scenario_records,
            projected_shortage_kwh=round(total_shortage_kwh, 2),
            worst_case_deficit_kw=round(worst_deficit_kw, 2),
            min_battery_soc_pct=round(min_soc, 1),
            min_hydrogen_level_pct=round(min_h2, 1),
            metadata={"config": config.model_dump()},
        )
