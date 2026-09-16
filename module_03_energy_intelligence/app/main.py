"""
Frost OS Module 03 — Main Application Entrypoint.

FastAPI application with lifespan management, structured logging,
MQTT telemetry subscriber, Redis Streams publisher, and WebSocket streaming.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.agents.energy_agent import EnergyAgent
from app.api.routes import router, set_engine_and_agent
from app.config.settings import Settings
from app.core.energy_engine import EnergyEngine
from app.events.publisher import EnergyEventPublisher
from app.models.energy_state import EnergyState
from app.mqtt.client import MQTTTelemetryClient
from app.storage.database import create_tables, dispose_engine, init_engine

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class WebSocketConnectionManager:
    """Manages active WebSocket connections for live EnergyState streaming."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_state(self, state: EnergyState):
        """Broadcast state JSON to all connected clients."""
        if not self.active_connections:
            return
        payload_str = json.dumps(state.model_dump(mode="json"))
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(payload_str)
            except Exception:
                disconnected.append(connection)
        for dead in disconnected:
            self.disconnect(dead)


ws_manager = WebSocketConnectionManager()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager."""
    settings = Settings()

    # 1. Initialize Database Engine & Schema
    init_engine(settings)
    await create_tables()
    await logger.ainfo("Energy Intelligence database initialized")

    # 2. Initialize Redis Client
    redis_client = None
    if not settings.mock_mode:
        try:
            import redis.asyncio as aioredis
            redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
            await redis_client.ping()
            await logger.ainfo("Connected to Redis", redis_url=settings.redis_url)
        except Exception as e:
            await logger.awarning("Redis connection unavailable; running in fallback mode", error=str(e))
            redis_client = None

    # 3. Initialize Core Engines & Services
    publisher = EnergyEventPublisher(redis_client, stream_name=settings.redis_stream_energy)
    engine = EnergyEngine(settings, publisher=publisher)
    agent = EnergyAgent(engine)

    # Wire up state callback for WebSocket broadcast
    async def on_state_computed(state: EnergyState) -> None:
        await ws_manager.broadcast_state(state)

    # 4. Initialize MQTT Subscriber Client
    async def on_mqtt_telemetry(records):
        state, alerts = await engine.process_telemetry(records)
        await on_state_computed(state)

    mqtt_client = MQTTTelemetryClient(settings, on_telemetry_callback=on_mqtt_telemetry)
    await mqtt_client.start()

    # Wire dependencies to API routes
    set_engine_and_agent(engine, agent)
    await logger.ainfo(
        "Frost OS Module 03 Energy Intelligence started",
        port=settings.service_port,
        mock_mode=settings.mock_mode,
    )

    yield

    # Shutdown logic
    await mqtt_client.stop()
    if redis_client:
        await redis_client.aclose()
    await dispose_engine()
    await logger.ainfo("Frost OS Module 03 Energy Intelligence shut down")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = Settings()

    application = FastAPI(
        title="Frost OS — Module 03: Energy Intelligence",
        description=(
            "Real-time energy telemetry, normalization, multi-carrier power balance, "
            "battery/hydrogen storage modeling, and anomaly detection for polar stations."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(router)

    @application.get("/health", tags=["System"])
    async def health_check():
        """Service liveness and health check."""
        return {
            "status": "healthy",
            "module": "module_03_energy_intelligence",
            "version": "0.1.0",
            "service": "Frost Energy Intelligence",
        }

    @application.websocket("/ws/energy/{station_id}")
    @application.websocket("/energy/stream")
    async def websocket_energy_stream(websocket: WebSocket, station_id: str = "halley_vi"):
        """WebSocket endpoint for real-time EnergyState telemetry stream."""
        await ws_manager.connect(websocket)
        try:
            while True:
                # Keep alive and receive any client pings
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            ws_manager.disconnect(websocket)
        except Exception:
            ws_manager.disconnect(websocket)

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn
    settings = Settings()
    uvicorn.run(
        "app.main:app",
        host=settings.service_host,
        port=settings.service_port,
        reload=settings.debug,
    )
