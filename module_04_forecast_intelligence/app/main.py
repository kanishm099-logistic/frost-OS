"""
Frost OS Module 04 — FastAPI Main Application & Lifespan.

Entry point for Module 04 Forecast Intelligence service.
Configures database initialization, Redis streams connection,
REST routing, and WebSocket forecast streaming.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import structlog

from app.api.routes import _publisher, router
from app.config.settings import get_settings
from app.storage.database import init_db

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: initialize database tables and Redis connections."""
    settings = get_settings()
    logger.info("module_04_starting", version=settings.app_version, env=settings.app_env)

    # Initialize DB tables (TimescaleDB or SQLite memory)
    try:
        await init_db()
        logger.info("database_tables_initialized")
    except Exception as e:
        logger.error("database_initialization_failed", error=str(e))

    # Connect Redis streams publisher
    try:
        await _publisher.connect()
    except Exception as e:
        logger.warning("redis_connection_warning", error=str(e))

    yield

    # Cleanup
    logger.info("module_04_shutting_down")
    await _publisher.close()


def create_app() -> FastAPI:
    """FastAPI application factory."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Predictive Weather, Renewable Generation, Station Load, Storage Trajectory & Energy-Risk Conditions",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix=settings.api_prefix)

    @app.get("/")
    async def root() -> dict[str, str]:
        return {
            "module": "Module 04: Forecast Intelligence",
            "system": "Frost OS — Polar Research Station Energy OS",
            "version": settings.app_version,
            "docs": "/docs",
        }

    @app.websocket("/forecasts/stream")
    async def websocket_forecast_stream(websocket: WebSocket):
        """WebSocket streaming live forecast updates and prediction intervals."""
        await websocket.accept()
        logger.info("websocket_client_connected", client=str(websocket.client))
        try:
            while True:
                # Poll or push recent events / forecast updates every 2 seconds
                published = _publisher.get_published_events()
                latest = published[-1] if published else {"type": "HEARTBEAT", "status": "LIVE"}
                await websocket.send_text(json.dumps(latest))
                await asyncio.sleep(2.0)
        except WebSocketDisconnect:
            logger.info("websocket_client_disconnected")
        except Exception as e:
            logger.warning("websocket_stream_exception", error=str(e))

    return app


app = create_app()
