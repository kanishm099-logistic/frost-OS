# 🛡️ Frost OS — Module 07: Safety + Reserve Intelligence

> **Autonomous, Resilient, and Independent Safety Barrier & Final Reserve Authority for Polar Microgrids.**

Module 07 is the final safety and reserve intelligence authority in **Frost OS**. It independently validates optimization plans proposed by Module 06 before they can be executed by Module 08.

---

## 🏛️ Core Principles

1. **Zero LLM in Safety Decision Path**: Safety decisions are 100% deterministic, backed by physics-informed reserve calculations, hard/soft constraint checking, and hardware emergency rules.
2. **Zero Silent Plan Relaxation**: Module 07 never mutates an unsafe plan into a safe plan. Unsafe plans are rejected or sent back for re-optimization (`REQUIRES_REPLAN`).
3. **Independent Plan Validation**: Module 07 recalculates power balances, storage trajectories, SOCs, hydrogen levels, and ramp rates without trusting Module 06 outputs.

---

## 📐 Dynamic 5-Component Reserve Model

Station energy reserve requirement is calculated dynamically via:

$$ \text{Reserve}_{\text{Protected}} = E_{\text{Station Continuity}} + E_{\text{Emergency}} + E_{\text{Mission Protected}} + E_{\text{Uncertainty Margin}} + E_{\text{Equipment Risk Margin}} + E_{\text{Operational Margin}} $$

### 5 Reserve Categories
1. `STATION_RESERVE_KWH`: Critical base load continuity over configured horizon (default 24h).
2. `MISSION_RESERVE_KWH`: Protected energy allocation for P0 life-support and P1 research missions.
3. `EMERGENCY_RESERVE_KWH`: Life-support & emergency evacuation buffer.
4. `OPERATIONAL_RESERVE_KWH`: Short-term spinning reserve & dynamic uncertainty/risk margins.
5. `TOTAL_PROTECTED_RESERVE_KWH`: Non-double-counted combined protected energy reserve.

---

## 🔄 Safety Decision State Machine

```
 RECEIVED ──► VALIDATING ──► RESERVE_CALCULATION ──► CONSTRAINT_CHECK ──► RISK_EVALUATION ──► DECISION
                                                                                                 │
                     ┌───────────────────┬───────────────────┬───────────────────┬───────────────┴───────────────┐
                     ▼                   ▼                   ▼                   ▼                               ▼
                 [ SAFE ]         [ CONDITIONAL ]    [ REQUIRES_REPLAN ]     [ UNSAFE ]                     [ EMERGENCY ]
```

---

## 🚀 Quick Start

### Running Tests
```bash
cd module_07_safety_reserve
pip install -r requirements.txt
pytest tests/ -v
```

### Running Service
```bash
uvicorn app.main:app --port 8007 --reload
```

---

## 🌐 API Overview

| Endpoint | Method | Description |
|---|---|---|
| `/safety/validate` | `POST` | Deterministic plan validation & safety decision |
| `/safety/validation/{id}` | `GET` | Retrieve validation by ID |
| `/safety/plan/{plan_id}` | `GET` | Retrieve latest validation for a plan |
| `/safety/reserve/{station_id}` | `GET` | Calculate current dynamic station reserves |
| `/safety/risk/{station_id}` | `GET` | Evaluate 8-category operational risks |
| `/safety/status/{station_id}` | `GET` | Subsystem operational status |
| `/safety/rules` | `GET` | Declarative safety rules registry |
| `/safety/policies` | `GET` | Active versioned policies |
| `/safety/simulate` | `POST` | Simulate validation under NORMAL, STORM, EMERGENCY scenarios |
| `/safety/audit/{plan_id}` | `GET` | Audit trail & state transitions |
| `/safety/stream` | `WS` | Real-time WebSocket safety event stream |
