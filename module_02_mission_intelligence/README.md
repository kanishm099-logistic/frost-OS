# Frost OS — Module 02: Mission Intelligence

Mission Intelligence is the cognitive workload management layer of **Frost OS**, the Agentic AI Energy Operating System for remote polar research stations.

---

## 1. Role & Architectural Boundaries

Module 02 makes Frost OS **mission-aware**. It answers:
- *What is the station doing?*
- *How important is each workload?*
- *How much power (kW) and energy (kWh) does it require?*
- *When does it need to run, and what is its hard deadline?*
- *How flexible is it (shiftable, interruptible, power-curtailable)?*
- *What protective energy buffer (kWh) must be preserved?*

### ⛔ Hard Architectural Constraints
- **NO Hardware Control**: Module 02 **never** issues commands to microgrids, generators, switches, or battery inverters (Module 08 Execution Gateway handles hardware translation).
- **NO Station-Wide Allocation**: Module 02 **describes** mission requirements and profiles; Module 06 Optimization Intelligence solves global multi-objective power routing.
- **NO Safety Override**: Module 02 **never** overrides physical limits or reserve envelopes owned by Module 07 Safety + Reserve Intelligence.

---

## 2. Core Workflow Pipeline

$$\text{Mission Input} \rightarrow \text{Classify} \rightarrow \text{Prioritize} \rightarrow \text{Estimate Energy} \rightarrow \text{Determine Flexibility} \rightarrow \text{Calculate Buffer} \rightarrow \text{Create Mission Profile} \rightarrow \text{Publish Event}$$

1. **Classify**: Deterministic rules map structured metadata and free-text descriptions into standard `MissionType`.
2. **Prioritize**: Multi-criteria priority scoring ($P0$ to $P4$) incorporating urgency, deadline pressure, mission value, flexibility, and energy efficiency. Hard protection for $P0$/$P1$.
3. **Estimate Energy**: Calculates $E = P \times t$ (kWh), distinguishing instantaneous power ($\text{kW}$) from energy over time ($\text{kWh}$). Supports min/max power and utilization factors.
4. **Minimum Power Guarantee**: Respects `min_power_kw`. A mission requiring 90 kW safe minimum power **cannot** be allocated 70 kW just because power is scarce.
5. **Determine Flexibility**: Classifies flexibility (`INFLEXIBLE`, `PARTIALLY_FLEXIBLE`, `FLEXIBLE`, `DEFERRABLE`) and computes earliest/latest start windows.
6. **Calculate Buffer**: Computes mission energy buffer in kWh ($\text{Buffer} = E \times \text{factor}$) to preserve critical margins.
7. **Create Profile**: Produces standardized `MissionProfile` consumable by Module 06 (Optimizer) and Module 01 (Orchestrator).
8. **Publish**: Emits `MISSION_*` events over Redis Streams.

---

## 3. Priority Levels

| Priority | Designation | Description | Buffer Factor |
|---|---|---|---|
| **P0** | Life & Safety Critical | Life support, habitat heating, emergency medical | +50% |
| **P1** | Mission Critical | Primary science research, core weather radar, vital comms | +30% |
| **P2** | Operationally Important | Laboratory sample analysis, maintenance routines | +15% |
| **P3** | Flexible | Heavy computing jobs, archival sync, non-urgent HVAC | +5% |
| **P4** | Deferrable | Recreational quarters, secondary convenience loads | 0% |

---

## 4. API Endpoints

- `POST /missions` — Create new mission
- `GET /missions` — List all missions
- `GET /missions/{mission_id}` — Get mission details
- `PATCH /missions/{mission_id}` — Update mission fields
- `DELETE /missions/{mission_id}` — Remove mission
- `POST /missions/{mission_id}/classify` — Classify mission type and initial priority
- `POST /missions/{mission_id}/profile` — Generate structured MissionProfile
- `POST /missions/{mission_id}/start` — Transition mission to RUNNING
- `POST /missions/{mission_id}/pause` — Transition mission to PAUSED
- `POST /missions/{mission_id}/complete` — Transition mission to COMPLETED
- `GET /missions/{mission_id}/energy-profile` — Detailed power and energy envelope
- `GET /missions/{mission_id}/priority` — Scheduling score and priority breakdown
- `GET /missions/{mission_id}/dependencies` — Upstream prerequisite dependency tree
- `GET /mission-intelligence/status` — Module operational status
- `GET /health` — Service liveness probe

### Module 01 & 06 Integration Interfaces
- `GET /missions/station/{station_id}/active` — Active missions for M01
- `GET /missions/station/{station_id}/priorities` — Priority summary for M01
- `POST /missions/station/{station_id}/impact-analysis` — Workload impact assessment on station events
- `GET /missions/profiles/active` — Active mission profiles for M06 Optimizer

---

## 5. Running Locally & Testing

```bash
# Set up virtual environment
uv venv
.\.venv\Scripts\activate
uv pip install -r requirements.txt

# Run full test suite
pytest -v

# Run polar station seed demo
python -m app.demo.seed_missions
```
