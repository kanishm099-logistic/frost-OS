# Frost OS — Module 03: Energy Intelligence

Energy Intelligence is the real-time physical telemetry aggregation and state-estimation layer of **Frost OS**, the Agentic AI Energy Operating System for remote polar research stations.

---

## 1. Role & Architectural Boundaries

Module 03 answers:
- *What is the station currently generating from solar, wind, and backup generators?*
- *What is the instantaneous total station electrical load?*
- *What is the net power balance (surplus or deficit)?*
- *What is the exact state-of-charge (SOC), available energy, and charge/discharge capability of the battery bank?*
- *What is the stored chemical energy and fuel cell capacity of the hydrogen system?*
- *Is the telemetry trusted, valid, and physically consistent?*

### ⛔ Hard Architectural Constraints
- **NO Strategic Allocation**: Module 03 observes and calculates physical availability; Module 06 Optimization Intelligence performs station-wide energy dispatch.
- **NO Direct Hardware Control**: Module 03 never commands inverters, switches, or battery breakers (Module 08 Gateway executes commands).
- **NO Safety Override**: Module 03 does not set emergency safety limits or station reserve rules (owned by Module 07 Safety + Reserve).

---

## 2. 13-Step Telemetry Processing Pipeline

$$\text{MQTT/HTTP Telemetry} \rightarrow \text{Validate} \rightarrow \text{Normalize} \rightarrow \text{Detect Bad Data} \rightarrow \text{Calculate Balance} \rightarrow \text{Storage State} \rightarrow \text{Anomalies} \rightarrow \text{Snapshot} \rightarrow \text{Publish}$$

1. **Ingest**: Receive high-frequency telemetry via MQTT topics or REST POST.
2. **Timestamp Validation**: Enforce UTC timezone awareness and clock skew sanity ($\le 60\text{s}$).
3. **Unit Normalization**: Convert W $\rightarrow$ kW, Wh $\rightarrow$ kWh, Celsius $\rightarrow$ Standard SI units.
4. **Range Checking**: Reject physically impossible readings (e.g. negative Kelvin, frequency $\le 0$, wind $> 120\text{ m/s}$).
5. **Quality Assignment**: Tag with `GOOD`, `SUSPECT`, `BAD`, `MISSING`, or `STALE`.
6. **Device State Update**: Update active device state in cache.
7. **Generation & Load Aggregation**: Group generation (solar, wind) and load (critical, flexible).
8. **Power Balance**: Compute $\text{Net} = \text{Generation} + \text{Discharge} + \text{Import} - \text{Load} - \text{Charge} - \text{Export}$.
9. **Numerical Integration**: Integrate $E = \int P \, dt$ over irregular $\Delta t$ intervals.
10. **Storage State & Derating**: Compute battery available energy with temperature derating and hydrogen usable energy.
11. **Anomaly & Residual Check**: Flag power balance discrepancies exceeding tolerance.
12. **Build EnergyState**: Generate immutable typed state snapshot.
13. **Publish & Broadcast**: Emit events to Redis Streams and broadcast over WebSocket (`/energy/stream`).

---

## 3. API Endpoints

- `POST /energy/telemetry` — Ingest telemetry record(s)
- `GET /energy/state` & `GET /energy/state/{station_id}` — Get latest EnergyState snapshot
- `GET /energy/generation` — Generation breakdown (solar, wind, generator)
- `GET /energy/load` — Load breakdown by category
- `GET /energy/storage` — Storage status (battery, hydrogen, thermal)
- `GET /energy/battery` — Detailed battery metrics & limits
- `GET /energy/hydrogen` — Detailed hydrogen reserve metrics
- `GET /energy/quality` — Telemetry data quality report
- `GET /energy/alerts` — Active energy alerts
- `GET /energy/history` — Time-series history
- `GET /energy-intelligence/status` — Service operational metrics
- `GET /health` — Service liveness probe
- `WebSocket /energy/stream` — Real-time live stream of EnergyState updates

### Inter-Module Integration Routes
- `GET /energy/station/{station_id}/status` — Compatible with Module 01 Orchestrator
- `POST /energy/station/{station_id}/analyze` — Generation event impact analysis for Module 01

---

## 4. Running Locally & Testing

```bash
# Set up virtual environment
uv venv
.\.venv\Scripts\activate
uv pip install -r requirements.txt

# Run full test suite
pytest -v

# Run polar station telemetry simulation
python -m app.telemetry.simulator
```
