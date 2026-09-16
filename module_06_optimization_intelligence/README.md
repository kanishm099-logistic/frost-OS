# ❄️ Frost OS — Module 06: Optimization Intelligence

> **Mathematical Decision & Energy Optimization Engine for Polar Microgrids**

Module 06 is the mathematical optimization operating component of **Frost OS**. It determines how available energy (wind, solar PV, battery energy storage, hydrogen fuel cells, electrolyzers) should be allocated over time across scientific missions, base loads, and energy storage while maximizing mission completion and system resilience without bypassing Module 07 Safety boundaries or directly controlling hardware.

---

## 🏛️ Architecture & Core Principles

```
  ┌───────────────────────────┐         ┌───────────────────────────┐
  │ Module 02: Mission Intel  │         │ Module 03: Energy Intel   │
  └─────────────┬─────────────┘         └─────────────┬─────────────┘
                │                                     │
                ▼                                     ▼
  ┌─────────────────────────────────────────────────────────────────┐
  │              Module 06: Optimization Intelligence              │
  │  (Model Builder -> MILP Solver -> Independent Deterministic    │
  │                  Plan Validator -> ActionPlan Proposal)         │
  └─────────────┬───────────────────────────────────────────────────┘
                │
                ▼
  ┌───────────────────────────┐         ┌───────────────────────────┐
  │  Module 01: Orchestrator  │ ◄────── │ Module 07: Safety &       │
  │ (Workflow & Action Plan)  │         │ Reserve Authority         │
  └───────────────────────────┘         └───────────────────────────┘
```

### Safety & Boundary Rules
1. **No Direct Hardware Control**: Module 06 generates actionable `ActionPlan` proposals for Module 01 (Orchestrator). Hardware execution is strictly delegated to Module 08.
2. **Module 07 Reserve Ownership**: Module 06 enforces M07 reserve bounds ($E_{\text{stored}}[t] \ge E_{\text{reserve}}$) at all time steps but **never** redefines safety thresholds.
3. **Independent Plan Validation**: All solver output passes through `PlanValidator` before returning. Unvalidated or constraint-violating plans are marked `INVALID` and rejected.
4. **Deterministic Mathematics**: No LLM-based numerical guessing or unverified heuristic allocation.

---

## 🚀 Quick Start

### Installation & Test Suite

```bash
# Navigate to module directory
cd module_06_optimization_intelligence

# Install dependencies
pip install -r requirements.txt

# Run full unit and integration test suite
python -m pytest tests/ -v
```

### Run 72-Hour Polar Station Simulation

```bash
python -m app.demo.simulation
```

### Start REST & WebSocket API Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8006 --reload
```

---

## 🛰️ REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/optimization/run` | Execute energy optimization for given inputs |
| `POST` | `/optimization/replan` | Rapid re-optimization upon subsystem trigger events |
| `POST` | `/optimization/scenarios` | Evaluate multi-scenario resilience suite |
| `GET` | `/optimization/{id}` | Retrieve optimization run payload by ID |
| `GET` | `/optimization/{id}/constraints` | Retrieve constraint summary and violations |
| `GET` | `/optimization/{id}/missions` | Retrieve mission power allocations |
| `GET` | `/optimization/{id}/storage` | Retrieve battery & hydrogen trajectories |
| `GET` | `/optimization/{id}/reserve` | Retrieve M07 station reserve trajectories |
| `GET` | `/optimization/{id}/explanation` | Retrieve objective breakdown & explanations |
| `POST` | `/optimization/validate` | Independent deterministic verification of candidate allocations |
| `GET` | `/health` | Service health status |
| `WS` | `/optimization/stream` | Real-time WebSocket stream |

---

## ⚡ Mathematical Formulation Summary

$$\begin{aligned}
\text{Maximize } Z &= w_{\text{mission}} \sum_{m, t} P_{m, t} \cdot \Delta t \cdot W_m + w_{\text{ren}} \sum_{t} P_{\text{renewable, used}}[t] \\
&- w_{\text{curtail}} \sum_t P_{\text{curtail}}[t] - w_{\text{cycling}} \sum_t (P_{\text{chg}}[t] + P_{\text{dis}}[t]) \Delta t - w_{\text{H2}} \sum_t P_{\text{H2, dis}}[t] \Delta t
\end{aligned}$$

**Subject to:**
1. **Power Balance**:
   $$P_{\text{solar}}[t] + P_{\text{wind}}[t] + P_{\text{batt, dis}}[t] + \eta_{\text{fc}} P_{\text{H2, dis}}[t] = P_{\text{load}}[t] + P_{\text{batt, chg}}[t] + P_{\text{H2, chg}}[t] + P_{\text{curtail}}[t] + \sum_m P_{m, t}$$
2. **Mission Bounds**:
   $$P_{m, \text{min}} \cdot u_{m, t} \le P_{m, t} \le P_{m, \text{max}} \cdot u_{m, t}, \quad u_{m, t} \in \{0, 1\}$$
3. **M07 Reserve Constraint**:
   $$E_{\text{batt}}[t] + E_{\text{H2}}[t] \ge E_{\text{reserve}}[t] \quad \forall t$$
