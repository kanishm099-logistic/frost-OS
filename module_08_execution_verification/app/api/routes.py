"""
Module 08 REST API Routes and WebSocket Handler.
"""

from __future__ import annotations

import json
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.config.settings import Settings, get_settings
from app.api.schemas import ExecutePlanHTTPRequest, ExecutePlanHTTPResponse, SystemStatusHTTPResponse
from app.core.execution_engine import ExecutionEngine
from app.hal.device_manager import HALDeviceManager
from app.devices.battery import BatteryDevice
from app.devices.wind import WindDevice
from app.devices.solar import SolarDevice
from app.devices.hydrogen import HydrogenDevice
from app.devices.inverter import InverterDevice
from app.devices.load import LoadDevice
from app.storage.repository import ExecutionRepository, get_db_session

logger = structlog.get_logger(__name__)

router = APIRouter()

_execution_cache: Dict[str, Any] = {}
_ws_connections: List[WebSocket] = []

# Singletons for HAL and Execution Engine
_settings = get_settings()
_device_manager = HALDeviceManager(_settings)

# Register default devices in HAL DeviceManager & connect them for execution
bat_dev = BatteryDevice("BAT-01")
bat_dev.is_connected = True
_device_manager.register_adapter("BAT-01", bat_dev)

wind_dev = WindDevice("WIND-01")
wind_dev.is_connected = True
_device_manager.register_adapter("WIND-01", wind_dev)

solar_dev = SolarDevice("SOLAR-01")
solar_dev.is_connected = True
_device_manager.register_adapter("SOLAR-01", solar_dev)

h2_dev = HydrogenDevice("H2-01")
h2_dev.is_connected = True
_device_manager.register_adapter("H2-01", h2_dev)

inv_dev = InverterDevice("INV-01")
inv_dev.is_connected = True
_device_manager.register_adapter("INV-01", inv_dev)

load_dev = LoadDevice("LOAD-01")
load_dev.is_connected = True
_device_manager.register_adapter("LOAD-01", load_dev)

_execution_engine = ExecutionEngine(_settings, _device_manager)


def get_engine() -> ExecutionEngine:
    return _execution_engine


def get_dev_manager() -> HALDeviceManager:
    return _device_manager


# ── Operational Status Endpoints ────────────────────────────────────

@router.get("/execution/history/{station_id}")
async def get_execution_history(station_id: str):
    """GET /execution/history/{station_id}"""
    return {
        "station_id": station_id,
        "history": list(_execution_cache.values()),
    }


@router.get("/execution/status", response_model=SystemStatusHTTPResponse)
@router.get("/execution-intelligence/status", response_model=SystemStatusHTTPResponse)
async def get_service_status(
    settings: Settings = Depends(get_settings),
    mgr: HALDeviceManager = Depends(get_dev_manager),
):
    """GET subsystem operational health."""
    return SystemStatusHTTPResponse(
        service="Module 08 Execution + Verification Intelligence",
        status="HEALTHY",
        station_id=settings.station_id,
        registered_devices_count=len(mgr.list_devices()),
        active_locks_count=0,
    )


@router.get("/execution/status/{station_id}", response_model=SystemStatusHTTPResponse)
async def get_station_status(
    station_id: str,
    mgr: HALDeviceManager = Depends(get_dev_manager),
):
    """GET subsystem status for station_id."""
    return SystemStatusHTTPResponse(
        service="Module 08 Execution + Verification Intelligence",
        status="HEALTHY",
        station_id=station_id,
        registered_devices_count=len(mgr.list_devices()),
        active_locks_count=0,
    )


# ── Execution Endpoints ─────────────────────────────────────────────

@router.post("/execution/plans/{plan_id}/execute", response_model=ExecutePlanHTTPResponse)
async def execute_authorized_plan(
    plan_id: str,
    req: ExecutePlanHTTPRequest,
    x_idempotency_key: Optional[str] = Header(default=None),
    engine: ExecutionEngine = Depends(get_engine),
    session: AsyncSession = Depends(get_db_session),
):
    """
    POST /execution/plans/{plan_id}/execute
    Execute an authorized ActionPlan. Enforces M01 auth, M07 SAFE status,
    local action limits, and telemetry verification.
    """
    idemp_key = req.idempotency_key or x_idempotency_key
    res = await engine.execute_plan(req.plan, idempotency_key=idemp_key)

    # Persist to Memory and DB
    _execution_cache[res["execution_id"]] = res
    _execution_cache[f"plan:{res['plan_id']}"] = res

    repo = ExecutionRepository(session)
    await repo.save_execution(res)

    await broadcast_ws_message({"type": "EXECUTION_COMPLETED", "execution_id": res["execution_id"], "status": res["status"]})

    return ExecutePlanHTTPResponse(
        success=(res["status"] == "COMPLETED"),
        status=res["status"],
        execution_id=res["execution_id"],
        plan_id=res["plan_id"],
        reason=res.get("reason"),
        verifications=res.get("verifications", []),
    )


@router.get("/execution/{execution_id}")
async def get_execution_by_id(
    execution_id: str,
    session: AsyncSession = Depends(get_db_session),
):
    """GET /execution/{execution_id}"""
    if execution_id in _execution_cache:
        return _execution_cache[execution_id]
    repo = ExecutionRepository(session)
    data = await repo.get_execution(execution_id)
    if not data:
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
    return data


@router.get("/execution/{execution_id}/actions")
async def get_execution_actions(execution_id: str):
    """GET /execution/{execution_id}/actions"""
    data = await get_execution_by_id(execution_id)
    return {
        "execution_id": execution_id,
        "actions": data.get("verifications", []),
    }


@router.get("/execution/{execution_id}/verification")
async def get_execution_verifications(execution_id: str):
    """GET /execution/{execution_id}/verification"""
    data = await get_execution_by_id(execution_id)
    return {
        "execution_id": execution_id,
        "verifications": data.get("verifications", []),
    }


@router.post("/execution/{execution_id}/cancel")
async def cancel_execution(execution_id: str):
    """POST /execution/{execution_id}/cancel"""
    return {"execution_id": execution_id, "status": "CANCELLED", "reason": "Operator requested cancellation"}


@router.post("/execution/{execution_id}/retry")
async def retry_execution(execution_id: str):
    """POST /execution/{execution_id}/retry"""
    return {"execution_id": execution_id, "status": "RETRY_QUEUED"}


# ── Device Management Endpoints ─────────────────────────────────────

@router.get("/devices")
async def list_devices(mgr: HALDeviceManager = Depends(get_dev_manager)):
    """GET /devices"""
    dev_ids = mgr.list_devices()
    result = []
    for d_id in dev_ids:
        adapter = mgr.get_adapter(d_id)
        if adapter:
            result.append(await adapter.get_state())
    return {"devices": result}


@router.get("/devices/{device_id}")
async def get_device_info(device_id: str, mgr: HALDeviceManager = Depends(get_dev_manager)):
    """GET /devices/{device_id}"""
    adapter = mgr.get_adapter(device_id)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not registered")
    return await adapter.get_state()


@router.get("/devices/{device_id}/state")
async def get_device_state(device_id: str, mgr: HALDeviceManager = Depends(get_dev_manager)):
    """GET /devices/{device_id}/state"""
    return await get_device_info(device_id, mgr)


@router.get("/devices/{device_id}/capabilities")
async def get_device_capabilities(device_id: str, mgr: HALDeviceManager = Depends(get_dev_manager)):
    """GET /devices/{device_id}/capabilities"""
    adapter = mgr.get_adapter(device_id)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not registered")
    return {
        "device_id": device_id,
        "capabilities": adapter.capabilities,
    }


@router.post("/devices/{device_id}/health-check")
async def device_health_check(device_id: str, mgr: HALDeviceManager = Depends(get_dev_manager)):
    """POST /devices/{device_id}/health-check"""
    adapter = mgr.get_adapter(device_id)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not registered")
    healthy = await adapter.health_check()
    return {"device_id": device_id, "healthy": healthy}


@router.get("/health")
async def health_check():
    """Liveness probe."""
    return {
        "service": "Module 08 Execution + Verification Intelligence",
        "status": "HEALTHY",
        "version": "1.0.0",
    }


@router.websocket("/execution/stream")
async def websocket_stream(websocket: WebSocket):
    """WebSocket stream endpoint for real-time execution status and events."""
    await websocket.accept()
    _ws_connections.append(websocket)
    logger.info("WebSocket client connected to /execution/stream")
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(json.dumps({"event": "PONG", "received": data}))
    except WebSocketDisconnect:
        _ws_connections.remove(websocket)
        logger.info("WebSocket client disconnected")


async def broadcast_ws_message(msg: Dict[str, Any]):
    for ws in list(_ws_connections):
        try:
            await ws.send_text(json.dumps(msg))
        except Exception:
            _ws_connections.remove(ws)
