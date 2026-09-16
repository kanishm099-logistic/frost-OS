# Module 05: Diagnostic Intelligence — Frost OS

> **Polar Microgrid Diagnostic Intelligence Service**  
> Telemetry validation, anomaly detection, health & degradation estimation, fault identification, and failure risk projection for polar research station microgrid infrastructure.

---

## Overview

Module 05 monitors equipment telemetry from critical station infrastructure:
- **Wind Turbines** (vibration, bearing temp, gearbox pressure, blade icing, generator output)
- **Solar PV Arrays** (irradiance, snow coverage, soiling, string mismatch, inverter coupling)
- **Battery Energy Storage Systems (BESS)** (cell voltage divergence, thermal runaway precursor, capacity fade, internal resistance)
- **Hydrogen Storage & Fuel Cells** (membrane hydration, fuel cell degradation, electrolyzer efficiency, pressure containment)
- **Power Electronics & Ancillary** (inverters, DC-DC converters, heat pumps, backup diesel)

### Safety Boundary
Module 05 is strictly an **advisory and diagnostic intelligence module**. It:
- **Does NOT** directly command or control hardware.
- **Does NOT** perform station-wide optimization (Module 03 responsibility).
- **Does NOT** override safety-critical interlocks or emergency shutdowns (Module 07 Safety responsibility).

---

## Core Capabilities

1. **Telemetry Ingestion & Quality Control**:
   - Range validation against equipment-specific physical operating boundaries
   - Rate-of-change (spike/jump) detection
   - Stale/frozen sensor detection
   - Outlier removal and linear interpolation imputation
   - Feature engineering (rolling statistics, EWMA, divergence metrics)

2. **Multi-Model Anomaly Detection**:
   - Rule-based physical threshold engine
   - Statistical z-score and EWMA drift detector
   - Machine learning Isolation Forest & XGBoost residual models
   - Ensemble fusion with confidence scoring

3. **Equipment Health & Degradation**:
   - Degradation models (vibration fatigue, battery capacity fade, PV snow/soiling loss, H2 membrane resistance)
   - Remaining Useful Life (RUL) estimation with confidence intervals
   - State of Health (SOH) scoring (0.0 – 1.0)

4. **Probable Fault Identification**:
   - Equipment-specific fault pattern matching
   - Root cause hypothesis generation with probability ranking
   - Severity classification: `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`

5. **Failure Risk Projection**:
   - Probability of failure within standard time horizons (1h, 6h, 24h, 72h, 7d)
   - Consequence severity scoring and urgency classification
   - Recommended proactive mitigation actions

6. **Event Publishing & Diagnostic API**:
   - Redis Streams publishing for real-time station alerts
   - Fast REST API on port 8005 with OpenAPI documentation
   - Prometheus-compatible metrics endpoint

---

## Architecture & Pipeline

```
Raw Telemetry
      │
      ▼
Telemetry Processor (Validate → Clean → Impute → Features)
      │
      ▼
Actual vs Expected Model (Equipment Adapters)
      │
      ▼
Anomaly Engine (Physical Rules + Statistical + Isolation Forest Ensemble)
      │
      ▼
Health & Degradation Engine (Stress History → SOH → RUL)
      │
      ▼
Fault Identification Engine (Pattern Signature Matching)
      │
      ▼
Failure Risk Engine (Hazard Rates → Multi-Horizon Probability)
      │
      ▼
Diagnostic Result & Alert Publisher (Redis Streams + TimescaleDB)
```

---

## API Endpoints

- `GET /health` — Service health & readiness check
- `POST /api/v1/telemetry/ingest` — Ingest raw telemetry batch
- `POST /api/v1/diagnostics/evaluate` — Run ad-hoc diagnostic evaluation
- `GET /api/v1/diagnostics/latest/{equipment_id}` — Get latest diagnostic report
- `GET /api/v1/equipment` — List registered equipment adapters
- `GET /api/v1/anomalies/active` — List currently active anomalies
- `GET /api/v1/risks/summary` — Station-wide risk summary
- `GET /metrics` — Prometheus metrics

---

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Run test suite
pytest tests/ -v

# Start service
uvicorn app.main:app --host 0.0.0.0 --port 8005 --reload
```

## Docker Deployment

```bash
docker-compose up -d
```
