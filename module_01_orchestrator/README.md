# ❄️ Frost OS — Module 01: Frost Orchestrator

**Event-driven coordination and decision-management layer** for Frost OS, an Agentic AI Energy Operating System for remote polar research stations.

Module 01 transforms station events into validated, explainable, authorized action plans. It coordinates specialist Modules 02–08 but **never** performs hardware control or electrical optimization itself.

---

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │       Module 01: Orchestrator        │
                    │                                      │
  Station Event ───►│  Validate → Classify → Route         │
                    │       │                              │
                    │       ▼                              │
                    │  ┌─────────────────────────────┐     │
                    │  │    Workflow Engine            │     │
                    │  │  (generation_drop,            │     │
                    │  │   mission_start,              │     │
                    │  │   equipment_failure,           │     │
                    │  │   low_reserve,                │     │
                    │  │   weather_risk)               │     │
                    │  └──────────┬──────────────────┘     │
                    │             │                        │
                    │    ┌────────▼────────────┐           │
                    │    │ Stage 1 (parallel)   │           │
                    │    │ Energy + Forecast    │           │
                    │    │ + Diagnostic + Mission│          │
                    │    └────────┬────────────┘           │
                    │             │                        │
                    │    ┌────────▼────────────┐           │
                    │    │ Stage 2 (sequential) │           │
                    │    │ Optimizer            │           │
                    │    └────────┬────────────┘           │
                    │             │                        │
                    │    ┌────────▼────────────┐           │
                    │    │ Stage 3 (sequential) │           │
                    │    │ Reserve + Safety     │           │
                    │    └────────┬────────────┘           │
                    │             │                        │
                    │    ┌────────▼────────────┐           │
                    │    │ Action Plan Builder  │           │
                    │    │ + Authorization      │           │
                    │    └────────┬────────────┘           │
                    │             │                        │
                    │    ┌────────▼────────────┐           │
                    │    │ M08 Execution        │           │
                    │    │ + Verification       │           │
                    │    └─────────────────────┘           │
                    └──────────────────────────────────────┘
```

### Module Communication

| Module | Role | Communication |
|--------|------|---------------|
| M02 Mission Intelligence | Active missions, priorities | REST |
| M03 Energy Intelligence | Generation/consumption status | REST |
| M04 Forecast Intelligence | Weather & generation forecasts | REST |
| M05 Diagnostic Intelligence | Equipment health & diagnostics | REST |
| M06 Optimization Intelligence | Resource allocation optimization | REST |
| M07 Safety+Reserve Intelligence | Reserve validation & safety checks | REST |
| M08 Execution+Verification | Hardware command execution | REST |

### Decision State Machine

```
DETECTED → ANALYZING → PREDICTED → OPTIMIZING → VALIDATING
    → AWAITING_AUTHORIZATION → AUTHORIZED → EXECUTING
    → VERIFYING → COMPLETED

Failure paths: REJECTED, REOPTIMIZING, EXECUTION_FAILED, CANCELLED
Emergency: VALIDATING → AUTHORIZED (skip human approval)
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/orchestrator/events` | Ingest a new station event |
| GET | `/orchestrator/events/{event_id}` | Retrieve event details |
| GET | `/orchestrator/decisions/{decision_id}` | Retrieve decision with transitions |
| GET | `/orchestrator/action-plans/{plan_id}` | Retrieve action plan |
| POST | `/orchestrator/action-plans/{plan_id}/authorize` | Approve plan for execution |
| POST | `/orchestrator/action-plans/{plan_id}/reject` | Reject plan |
| GET | `/orchestrator/status` | System status overview |
| GET | `/orchestrator/workflows/{workflow_id}` | Workflow run details |
| GET | `/health` | Health check (DB + Redis) |
| WS | `/orchestrator/ws` | Live orchestration updates |

### Example: Submit Event

```bash
curl -X POST http://localhost:8000/orchestrator/events \
  -H "Content-Type: application/json" \
  -d '{
    "source": "wind-sensor-array-01",
    "event_type": "WIND_POWER_DROP",
    "severity": "HIGH",
    "station_id": "FROST-STATION-ALPHA",
    "payload": {
      "previous_kw": 180.0,
      "current_kw": 70.0
    }
  }'
```

### Example: Authorize Plan

```bash
curl -X POST http://localhost:8000/orchestrator/action-plans/{plan_id}/authorize \
  -H "Content-Type: application/json" \
  -d '{
    "authorized_by": "dr-sarah-chen",
    "reason": "Reviewed and approved"
  }'
```

---

## Quick Start

### Docker (Recommended)

```bash
# Start all services
docker-compose up --build

# Verify health
curl http://localhost:8000/health

# Run the wind drop simulation
docker-compose exec orchestrator python -m app.demo.simulate_wind_drop
```

### Local Development

```bash
# Prerequisites: Python 3.12+, PostgreSQL, Redis

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export FROST_DATABASE_URL=postgresql+asyncpg://frost:frost_secret@localhost:5432/frost_orchestrator
export FROST_REDIS_URL=redis://localhost:6379/0
export FROST_MOCK_MODE=true

# Run the server
uvicorn app.main:app --reload --port 8000

# Run the simulation (standalone, no external services needed)
pip install aiosqlite  # For in-memory SQLite in demo
python -m app.demo.simulate_wind_drop
```

### Running Tests

```bash
# Install test dependencies
pip install aiosqlite  # For in-memory SQLite test database

# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing

# Run integration test only
pytest tests/test_integration.py -v
```

---

## Project Structure

```
module_01_orchestrator/
├── app/
│   ├── main.py                        # FastAPI app factory + lifespan
│   ├── api/
│   │   ├── routes.py                  # All REST + WebSocket endpoints
│   │   └── schemas.py                 # Pydantic v2 API schemas
│   ├── core/
│   │   ├── orchestrator.py            # Central coordination engine
│   │   ├── event_router.py            # Data-driven routing table
│   │   ├── workflow_engine.py         # Registry-based workflow dispatch
│   │   └── decision_manager.py        # State machine + plan builder
│   ├── agents/
│   │   └── orchestrator_agent.py      # Deterministic coordinator agent
│   ├── events/
│   │   ├── consumer.py                # Redis Streams consumer
│   │   ├── publisher.py               # Redis Streams publisher
│   │   └── event_types.py             # Stream/group constants
│   ├── clients/
│   │   ├── base_client.py             # Resilient HTTP base (retry+circuit breaker)
│   │   ├── mission_client.py          # M02 client + mock
│   │   ├── energy_client.py           # M03 client + mock
│   │   ├── forecast_client.py         # M04 client + mock
│   │   ├── diagnostic_client.py       # M05 client + mock
│   │   ├── optimizer_client.py        # M06 client + mock
│   │   ├── reserve_client.py          # M07 client + mock
│   │   └── execution_client.py        # M08 client + mock
│   ├── workflows/
│   │   ├── generation_drop.py         # WIND_POWER_DROP, SOLAR_OUTPUT_DROP, LOAD_SPIKE
│   │   ├── mission_start.py           # MISSION_STARTED, MISSION_DEADLINE_APPROACHING
│   │   ├── equipment_failure.py       # EQUIPMENT_DEGRADED, TURBINE_ANOMALY, COMMS_LOSS
│   │   ├── low_reserve.py             # BATTERY_LOW, HYDROGEN_LOW
│   │   └── weather_risk.py            # WEATHER_WARNING
│   ├── models/
│   │   ├── event.py                   # StationEvent + EventRecord ORM
│   │   ├── decision.py                # Decision state machine + ORM
│   │   └── action_plan.py             # ActionPlan + Authorization ORM
│   ├── storage/
│   │   ├── database.py                # Async engine + session factory
│   │   └── repository.py              # Data access repositories
│   ├── config/
│   │   └── settings.py                # Pydantic-settings config
│   └── demo/
│       └── simulate_wind_drop.py      # Standalone demo simulation
├── tests/
│   ├── conftest.py                    # Shared fixtures + factories
│   ├── test_events.py                 # Event validation + routing
│   ├── test_workflows.py             # Workflow registry + handlers
│   ├── test_decisions.py             # State machine + authorization
│   ├── test_orchestrator.py          # Full pipeline + agent tests
│   ├── test_api.py                   # API endpoint tests
│   └── test_integration.py           # WIND_POWER_DROP end-to-end
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## Key Design Decisions

### Data-Driven Routing (No If/Else)
The routing table in `event_router.py` maps every `EventType` to its severity, affected modules, and workflow — a pure dict lookup. Adding new event types requires only a new table entry.

### Dependency-Aware Parallel Execution
Independent module queries run via `asyncio.gather()`. Dependent stages (Optimizer needs analysis results, Reserve needs optimizer results) execute sequentially. This is enforced in each workflow handler.

### Mock Mode for Standalone Development
Set `FROST_MOCK_MODE=true` to use mock clients returning realistic data. The same orchestration code runs identically — only the client implementations change. Connecting to real Modules 02–08 requires only setting `FROST_MOCK_MODE=false` and providing service URLs.

### Circuit Breaker + Retry
Every module client inherits from `BaseModuleClient` which provides:
- Configurable timeout (default 30s)
- Retry with bounded exponential backoff (1s → 2s → 4s, max 3 attempts)
- Circuit breaker (5 failures → 30s open → half-open probe)
- Structured error responses (never raises to callers)

### Emergency Safety Bypass
If M07 flags an event as `is_emergency=True`, Module 01 skips human authorization and proceeds immediately. Module 01 **never** overrides M07 safety constraints.

### Every Transition is Audited
All state machine transitions, authorization decisions, workflow stages, and execution results are persisted with timestamps, actor identities, and correlation IDs.

---

## Connecting to Real Modules

When Modules 02–08 are available, set:

```bash
FROST_MOCK_MODE=false
FROST_MISSION_SERVICE_URL=http://module-02:8002
FROST_ENERGY_SERVICE_URL=http://module-03:8003
FROST_FORECAST_SERVICE_URL=http://module-04:8004
FROST_DIAGNOSTIC_SERVICE_URL=http://module-05:8005
FROST_OPTIMIZER_SERVICE_URL=http://module-06:8006
FROST_RESERVE_SERVICE_URL=http://module-07:8007
FROST_EXECUTION_SERVICE_URL=http://module-08:8008
```

No code changes required — the orchestration logic is identical.

---

## License

Frost OS — Internal Research Station Software
