# ❄️ Frost OS: Polar Microgrid Agentic AI Energy Operating System

> **Autonomous, resilient, and explainable energy intelligence and orchestration for remote polar research stations.**

Frost OS is an Agentic AI Energy Operating System designed to manage multi-source renewable microgrids (wind, solar PV, battery energy storage, hydrogen fuel cells/electrolyzers, and auxiliary power) operating under harsh Antarctic and Arctic environments.

---

## 🏛️ System Architecture & Modular Design

Frost OS is organized into specialized, loosely coupled microservices communicating via asynchronous event streams (Redis Streams) and REST APIs:

```
                                  ┌──────────────────────────────┐
                                  │   Module 01: Orchestrator    │
                                  │   (Coordination & Workflow)  │
                                  └──────────────┬───────────────┘
                                                 │
                   ┌─────────────────────────────┼─────────────────────────────┐
                   │                             │                             │
                   ▼                             ▼                             ▼
     ┌───────────────────────────┐ ┌───────────────────────────┐ ┌───────────────────────────┐
     │ Module 02: Mission Intel  │ │ Module 03: Energy Intel   │ │ Module 04: Forecast Intel │
     │ Priority & Load Demand    │ │ Microgrid Optimization    │ │ Weather & Load/Gen Models │
     └───────────────────────────┘ └───────────────────────────┘ └───────────────────────────┘
                                                 │
                                                 ▼
                                   ┌───────────────────────────┐
                                   │ Module 05: Diagnostic     │
                                   │ Telemetry, Health, Fault  │
                                   └───────────────────────────┘
```

### Module Summary

| Module | Name | Responsibility | Port |
|---|---|---|---|
| **Module 01** | **Orchestrator** | Event validation, workflow orchestration, explainable multi-stage decision plans | `8001` |
| **Module 02** | **Mission Intelligence** | Scientific activity tracking, priority weighting, critical power rationing | `8002` |
| **Module 03** | **Energy Intelligence** | Power flow optimization, battery cycling, hydrogen dispatch, reserve management | `8003` |
| **Module 04** | **Forecast Intelligence** | Numerical weather prediction ingestion, renewable generation & polar load forecasting | `8004` |
| **Module 05** | **Diagnostic Intelligence** | Equipment telemetry quality control, anomaly detection, SOH/RUL degradation & failure risk | `8005` |

---

## 🔒 Safety First Operating Principles

- **No Direct Hardware Control**: Advisory modules emit actionable recommendations; physical actuations are mediated and strictly validated.
- **Fail-Safe Fallbacks**: Graceful degradation under telemetry dropouts, sensor freeze, or subsystem disconnects.
- **Explainability**: Every recommendation carries machine-readable rationales, confidence intervals, and risk bounds.
- **Polar Hardened**: Physics-informed degradation models account for sub-zero temperatures, blade icing, and drifting snow.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Docker & Docker Compose
- Git

### Running Individual Modules
Navigate to any module directory to run tests or start the service:

```bash
# Example: Module 05 Diagnostic Intelligence
cd module_05_diagnostic_intelligence
pip install -r requirements.txt
pytest tests/ -v
uvicorn app.main:app --port 8005 --reload
```
