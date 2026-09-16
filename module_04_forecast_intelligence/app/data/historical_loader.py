"""
Frost OS Module 04 — Historical Data & Telemetry Loader.

Synthesizes and loads 72-hour historical time-series datasets for polar research stations,
including austral summer (continuous solar), winter (polar night), and wind collapse regimes.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from app.models.weather import WeatherCondition, WeatherObservation


class HistoricalDataLoader:
    """Provides historical training and evaluation datasets for polar research stations."""

    def __init__(
        self,
        station_id: str = "polar-station-alpha",
        latitude: float = -75.58,
        longitude: float = -26.66,
    ) -> None:
        self.station_id = station_id
        self.latitude = latitude
        self.longitude = longitude

    def generate_synthetic_history(
        self,
        hours: int = 72,
        season: str = "summer",
        include_wind_collapse: bool = False,
        end_time: datetime | None = None,
    ) -> pd.DataFrame:
        """
        Generate 15-minute resolution historical time series.
        Columns:
          - timestamp (UTC)
          - temperature_c
          - wind_speed_ms
          - cloud_cover_pct
          - solar_irradiance_wm2
          - solar_elevation_deg
          - air_density_kgm3
          - solar_generation_kw
          - wind_generation_kw
          - total_renewable_generation_kw
          - station_load_kw
          - battery_soc_pct
          - battery_energy_kwh
          - hydrogen_level_pct
        """
        now = end_time or datetime.now(timezone.utc)
        start = now - timedelta(hours=hours)

        periods = int(hours * 4)  # 15-min intervals
        timestamps = [start + timedelta(minutes=15 * i) for i in range(periods)]

        is_summer = season.lower() == "summer"
        base_temp = -14.0 if is_summer else -36.0

        records = []
        soc = 82.0
        h2 = 78.0

        for i, ts in enumerate(timestamps):
            day_of_year = ts.timetuple().tm_yday
            hour_frac = ts.hour + ts.minute / 60.0

            # Solar elevation
            delta = 23.45 * math.sin(math.radians(360.0 / 365.0 * (day_of_year - 81)))
            hour_angle = 15.0 * (hour_frac - (12.0 - self.longitude / 15.0))
            lat_r = math.radians(self.latitude)
            del_r = math.radians(delta)
            ha_r = math.radians(hour_angle)

            sin_elev = math.sin(lat_r) * math.sin(del_r) + math.cos(lat_r) * math.cos(del_r) * math.cos(ha_r)
            elev_deg = math.degrees(math.asin(max(-1.0, min(1.0, sin_elev))))

            # Cloud cover: sinusoids with noise
            cloud = min(100.0, max(0.0, 40.0 + 35.0 * math.sin(i * 0.05) + 10.0 * math.cos(i * 0.12)))

            # Temperature
            temp = base_temp + 3.5 * math.sin(hour_frac * math.pi / 12.0) - 2.0 * (cloud / 100.0)

            # Air density
            p_hpa = 982.0 + 5.0 * math.cos(i * 0.02)
            temp_k = temp + 273.15
            rho = (p_hpa * 100.0) / (287.058 * temp_k)

            # Wind speed
            base_wind = 10.5 + 4.0 * math.cos(i * 0.04)
            if include_wind_collapse and i >= (periods * 0.7):
                # Wind drops sharply in last 30% of timeline
                collapse_factor = max(0.1, 1.0 - (i - periods * 0.7) / (periods * 0.15))
                wind_speed = max(0.8, base_wind * collapse_factor)
            else:
                wind_speed = max(0.0, base_wind + 1.2 * math.sin(i * 0.3))

            # Solar generation
            if is_summer and elev_deg > 0:
                raw_irradiance = 1050.0 * math.sin(math.radians(elev_deg))
                attenuation = (1.0 - 0.75 * (cloud / 100.0) ** 1.8)
                eff_irradiance = max(0.0, raw_irradiance * attenuation)
                # 80 kW peak array, ~420 m2 area, 19% efficiency, cold temp boost (+0.4% per °C below 25°C)
                temp_boost = 1.0 + (-0.004 * (temp - 25.0))
                solar_kw = min(80.0, max(0.0, (eff_irradiance * 420.0 * 0.19 / 1000.0) * temp_boost))
            else:
                eff_irradiance = 0.0
                solar_kw = 0.0

            # Wind generation (120 kW nameplate, cut-in 3, rated 12, cut-out 25)
            if wind_speed < 3.0 or wind_speed > 25.0:
                wind_kw = 0.0
            elif wind_speed >= 12.0:
                # Rated speed up to cut-out
                wind_kw = 120.0
            else:
                # Cubic region adjusted for cold polar air density: P = 0.5 * rho * A * v^3 * Cp
                area = math.pi * (10.0 ** 2) * 2  # 2 turbines of 20m diameter
                theoretical_p = 0.5 * rho * area * (wind_speed ** 3) * 0.42 / 1000.0
                wind_kw = min(120.0, max(0.0, theoretical_p))

            total_gen_kw = solar_kw + wind_kw

            # Station load: 35 kW base + heating sensitivity + diurnal lab activity
            heating_load = max(0.0, (18.0 - temp) * 0.85)
            lab_activity = 12.0 * math.sin(max(0.0, math.pi * (hour_frac - 8) / 10.0)) if 8 <= hour_frac <= 18 else 2.0
            load_kw = max(25.0, 35.0 + heating_load + lab_activity)

            # Update battery SOC based on net balance
            net_kw = total_gen_kw - load_kw
            dt_hours = 0.25  # 15 mins
            if net_kw >= 0:
                # Charging: efficiency 92%
                delta_kwh = net_kw * dt_hours * 0.92
                soc = min(95.0, soc + (delta_kwh / 500.0) * 100.0)
            else:
                # Discharging
                delta_kwh = abs(net_kw) * dt_hours / 0.92
                soc = max(15.0, soc - (delta_kwh / 500.0) * 100.0)

            # Hydrogen buffer varies slowly
            if soc > 90.0 and net_kw > 20.0:
                h2 = min(98.0, h2 + 0.05)
            elif soc < 25.0 and net_kw < -15.0:
                h2 = max(10.0, h2 - 0.08)

            records.append({
                "timestamp": ts,
                "temperature_c": round(temp, 2),
                "wind_speed_ms": round(wind_speed, 2),
                "cloud_cover_pct": round(cloud, 1),
                "solar_irradiance_wm2": round(eff_irradiance, 1),
                "solar_elevation_deg": round(elev_deg, 2),
                "air_density_kgm3": round(rho, 4),
                "solar_generation_kw": round(solar_kw, 2),
                "wind_generation_kw": round(wind_kw, 2),
                "total_renewable_generation_kw": round(total_gen_kw, 2),
                "station_load_kw": round(load_kw, 2),
                "battery_soc_pct": round(soc, 1),
                "battery_energy_kwh": round(soc * 5.0, 1),
                "hydrogen_level_pct": round(h2, 1),
            })

        return pd.DataFrame(records)

    def generate_weather_observations(
        self, df_history: pd.DataFrame
    ) -> list[WeatherObservation]:
        """Convert historical dataframe to list of WeatherObservation domain models."""
        obs_list = []
        for _, row in df_history.iterrows():
            cond = WeatherCondition.CLEAR
            if row["cloud_cover_pct"] > 80:
                cond = WeatherCondition.OVERCAST
            elif row["cloud_cover_pct"] > 40:
                cond = WeatherCondition.PARTLY_CLOUDY
            if row["wind_speed_ms"] > 20:
                cond = WeatherCondition.STORM

            obs_list.append(
                WeatherObservation(
                    station_id=self.station_id,
                    timestamp=row["timestamp"],
                    temperature_c=row["temperature_c"],
                    wind_speed_ms=row["wind_speed_ms"],
                    cloud_cover_pct=row["cloud_cover_pct"],
                    global_horizontal_irradiance_wm2=row["solar_irradiance_wm2"],
                    condition=cond,
                    source="historical_telemetry",
                )
            )
        return obs_list
