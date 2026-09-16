# ⚙️ Frost OS — Module 08: Execution + Verification Intelligence

> **Controlled Actuator Gateway & Hardware Verification Intelligence for Polar Research Station Microgrids.**

Module 08 is the controlled execution layer of **Frost OS**. It receives authorized action plans from Module 01 and Module 07, translates high-level actions into device protocol commands (Modbus, OPC-UA, CAN, MQTT), executes commands through a Hardware Abstraction Layer (HAL), and verifies actual system telemetry against expected setpoints.

---

## 🏛️ Core Principles

1. **Actuator Gateway**: Module 08 executes ONLY authorized plans from M01/M07. It never invents actions, modifies plans, or overrides safety decisions.
2. **Zero Raw Register Public API**: Frontend and optimizers cannot send raw register writes or CAN frames. All interactions use high-level typed actions (`CHARGE_BATTERY`, `DISCHARGE_BATTERY`, `SET_MISSION_POWER`, `CURTAIL_RENEWABLE`, etc.).
3. **Telemetry Verification**: Verification uses actual physical telemetry observation over time windows within configurable tolerance bands ($\pm 5\text{ kW}$), not command acknowledgements alone.
4. **Hardware Safety Interlocks**: Hardware-native emergency limits are authoritative and can never be overridden by software.

---

## 🔄 Execution State Machine

```
 RECEIVED ──► AUTH_CHECK ──► SAFETY_CHECK ──► VALIDATING ──► QUEUED ──► EXECUTING ──► OBSERVING ──► VERIFYING ──► COMPLETED
                                                                                                        │
                  ┌───────────────────┬───────────────────┬───────────────────┬─────────────────────────┴─────────────────────────┐
                  ▼                   ▼                   ▼                   ▼                                                   ▼
             [ REJECTED ]        [ EXPIRED ]         [ TIMEOUT ]     [ EXECUTION_FAILED ]                               [ VERIFICATION_FAILED ]
```

---

## 🚀 Quick Start

### Running Tests
```bash
cd module_08_execution_verification
pip install -r requirements.txt
pytest tests/ -v
```

### Running Service
```bash
uvicorn app.main:app --port 8008 --reload
```

---

## 🌐 API Overview

| Endpoint | Method | Description |
|---|---|---|
| `/execution/plans/{plan_id}/execute` | `POST` | Execute authorized ActionPlan with validation & verification |
| `/execution/{execution_id}` | `GET` | Retrieve execution details |
| `/execution/{execution_id}/actions` | `GET` | Retrieve action progress |
| `/execution/{execution_id}/verification` | `GET` | Retrieve telemetry verification results |
| `/execution/{execution_id}/cancel` | `POST` | Cancel execution |
| `/devices` | `GET` | List registered HAL hardware devices & states |
| `/devices/{device_id}` | `GET` | Get single device info |
| `/devices/{device_id}/capabilities` | `GET` | Inspect device boundary limits |
| `/devices/{device_id}/health-check` | `POST` | Trigger hardware health check |
| `/execution/status` | `GET` | Service operational status |
| `/execution/stream` | `WS` | Real-time WebSocket execution event stream |
