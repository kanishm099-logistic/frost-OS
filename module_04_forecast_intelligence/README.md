# Frost OS — Module 04: Forecast Intelligence

> **Agentic AI Energy Operating System for Remote Polar Research Stations**
> Module 04: Predictive Weather, Renewable Generation, Station Load, Storage Trajectory & Energy-Risk Analytics.

---

## 1. System Role & Architecture

Module 04 predicts future weather conditions, renewable generation (solar PV & wind turbines), station demand (critical, operational, flexible), battery/hydrogen storage trajectories, and energy shortage risks.

### System Boundaries
- **Consumes**:
  - Module 03 `EnergyState` (current ground truth electrical & thermodynamic state)
  - Module 02 `MissionProfile` (scheduled and active research missions P0–P4)
  - Module 05 `EquipmentHealth` (turbine icing, inverter degradation derating factors)
  - External NWP / weather forecast observations (via modular adapter interface)
- **Provides Advisory Inputs To**:
  - Module 01 `Frost Orchestrator` (trend alerts, generation drops, weather warnings)
  - Module 06 `Optimization Intelligence` (probabilistic generation/load forecasts & scenarios)
  - Module 07 `Safety & Reserve Intelligence` (conservative 10th percentile bounds & shortage probabilities)
- **Strict Boundary Enforcements**:
  - **Does NOT** directly command hardware (Module 08 Gateway executes dispatch).
  - **Does NOT** allocate or schedule missions (Module 02 & 06 handle missions).
  - **Does NOT** override safety or reserve margins (Module 07 enforces safety).

---

## 2. Forecast Targets & Horizons

### 10 Forecast Targets
1. `solar_generation_kw`: Solar PV generation with astronomical solar angle & cloud attenuation.
2. `wind_generation_kw`: Wind generation with cold-air density boost ($\rho \approx 1.45\text{ kg/m}^3$) and turbine limits.
3. `total_renewable_generation_kw`: Sum of solar + wind generation.
4. `station_load_kw`: Station electrical demand with baseline heating and mission P0–P4 metadata.
5. `battery_soc_pct`: State of Charge trajectory under passive and scenario dispatch.
6. `battery_energy_kwh`: Usable battery energy trajectory.
7. `hydrogen_level_pct`: Fuel cell / electrolyzer buffer trajectory.
8. `energy_surplus_deficit_kw`: Instantaneous projected net power balance.
9. `energy_shortage_risk`: Probabilistic shortage risk classification (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
10. `renewable_availability`: Availability index based on wind speeds within $[v_{cut-in}, v_{cut-out}]$ and solar elevations.

### 8 Configurable Horizons
- `5m`, `15m`, `30m`, `1h`, `6h`, `24h`, `48h`, `72h`.

---

## 3. Physical Models & ML Strategies

- **Solar PV**: Clear-sky radiation baseline + solar elevation angle $\alpha = \arcsin(\sin \phi \sin \delta + \cos \phi \cos \delta \cos \omega)$ + temperature coefficient correction + XGBoost cloud attenuation model. Handles polar day (continuous 24h sun) and polar night ($\alpha < 0^\circ$).
- **Wind Turbine**: Physical cubic power curve $P(v) = \frac{1}{2}\rho A v^3 C_p$ adjusted for polar air density $\rho = \frac{P_{atm}}{R_{spec} \cdot T}$ + cut-in ($3.0\text{ m/s}$), rated ($12.0\text{ m/s}$), and cut-out ($25.0\text{ m/s}$) limits + turbine icing derating + XGBoost residual correction.
- **Station Demand**: Base life support + temperature sensitivity ($\Delta P \propto (T_{target} - T_{ambient})$) + active mission requirements + gradient boosting residual model.
- **Uncertainty**: Quantile-based expanding prediction intervals ($q_{10}, q_{50}, q_{90}$) scaled with lead-time uncertainty $\sigma(t) = \sigma_0 \sqrt{1 + \beta t}$. Stale or missing telemetry triggers confidence penalties and interval widening.

---

## 4. Operational Scenarios (9 Scenarios)
1. `BASELINE`: NWP and ML point forecast.
2. `LOW_RENEWABLE`: Combined 10th-percentile wind and 80% cloud cover solar suppression.
3. `HIGH_RENEWABLE`: 90th-percentile wind and clear-sky solar.
4. `HIGH_LOAD`: +25% heating load from extreme polar chill and concurrent mission execution.
5. `LOW_WIND`: Stagnant polar high-pressure ridge ($<3.0\text{ m/s}$).
6. `SOLAR_DROP`: Blizzard/heavy cloud attenuation ($>95\%$ overcast).
7. `STORM`: Catabatic storm event exceeding $25\text{ m/s}$ causing turbine cut-out shutdown.
8. `EQUIPMENT_DEGRADATION`: Blade icing and inverter derating applied from Module 05.
9. `COMMUNICATION_LOSS`: NWP stale, persistence model fallback with widened prediction intervals.

---

## 5. API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/forecasts/generate` | Trigger on-demand multi-target forecast run |
| `GET` | `/forecasts` | List past forecast runs |
| `GET` | `/forecasts/{forecast_id}` | Retrieve forecast run details and target time-series |
| `GET` | `/forecasts/stations/{station_id}` | Latest 72h forecast overview for a station |
| `GET` | `/forecasts/stations/{station_id}/generation` | Solar & wind generation forecasts |
| `GET` | `/forecasts/stations/{station_id}/load` | Station demand forecasts |
| `GET` | `/forecasts/stations/{station_id}/storage` | Passive & scenario battery SOC / hydrogen projections |
| `GET` | `/forecasts/stations/{station_id}/risk` | Probabilistic shortage risk assessment |
| `POST` | `/forecasts/scenarios` | Generate 9 what-if operational scenarios |
| `GET` | `/forecasts/scenarios/{scenario_id}` | Retrieve scenario forecasts |
| `GET` | `/models` | Model registry listing models, versions, and metrics |
| `GET` | `/models/{model_name}` | Details for specific ML model |
| `POST` | `/models/{model_name}/train` | Trigger model retraining run |
| `POST` | `/models/{model_name}/validate` | Validate model against test split |
| `GET` | `/forecast-intelligence/status` | Ingestion status, model versions, cache health |
| `GET` | `/health` | Health check endpoint |
| `WS` | `/forecasts/stream` | WebSocket streaming updated forecast intervals |
| `GET` | `/forecast/station/{station_id}` | **Module 01 Compatibility**: generation trend & horizons |
| `GET` | `/forecast/station/{station_id}/weather` | **Module 01 Compatibility**: weather forecast snapshot |
