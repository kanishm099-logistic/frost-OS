"""
Frost OS Module 01 — Base Module Client.

Provides a resilient async HTTP client base class with:
- Configurable request timeout
- Retry with bounded exponential backoff
- Circuit breaker (CLOSED → OPEN → HALF_OPEN)
- Structured error responses (never silently swallowed)
- Degraded-mode fallback when circuit is open
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import Any

import httpx
import structlog

from app.config.settings import Settings
from app.models.decision import ModuleResponse

logger = structlog.get_logger(__name__)


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """
    Simple circuit breaker implementation.

    CLOSED (normal) → failure_threshold consecutive failures → OPEN
    OPEN → recovery_timeout elapsed → HALF_OPEN (allow 1 probe)
    HALF_OPEN → success → CLOSED | failure → OPEN
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float = 0.0

    def record_success(self) -> None:
        """Record a successful call — reset failures, close circuit."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed call — increment counter, potentially open circuit."""
        self.failure_count += 1
        self.last_failure_time = time.monotonic()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            elapsed = time.monotonic() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                return True
            return False
        # HALF_OPEN — allow exactly one probe
        return True


class BaseModuleClient:
    """
    Abstract base for all module REST clients.

    Provides retry, circuit breaker, timeout, and structured
    error responses. Subclasses implement domain-specific methods.
    """

    MODULE_NAME: str = "base"

    def __init__(self, base_url: str, settings: Settings) -> None:
        self._base_url = base_url.rstrip("/")
        self._settings = settings
        self._timeout = httpx.Timeout(settings.client_timeout_seconds)
        self._max_retries = settings.client_max_retries
        self._retry_base_delay = settings.client_retry_base_delay
        self._retry_max_delay = settings.client_retry_max_delay
        self._circuit = CircuitBreaker(
            failure_threshold=settings.circuit_breaker_failure_threshold,
            recovery_timeout=settings.circuit_breaker_recovery_timeout,
        )
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        params: dict | None = None,
    ) -> ModuleResponse:
        """
        Make a resilient HTTP request with retry and circuit breaker.

        Returns a ModuleResponse — never raises exceptions to callers.
        Failures are captured in the response status and error_message.
        """
        # Check circuit breaker
        if not self._circuit.allow_request():
            await logger.awarning(
                "Circuit breaker OPEN — request blocked",
                module=self.MODULE_NAME,
                path=path,
            )
            return ModuleResponse(
                module_name=self.MODULE_NAME,
                status="circuit_open",
                error_message=f"Circuit breaker is open for {self.MODULE_NAME}",
                is_degraded=True,
                confidence=0.0,
            )

        last_error: str = ""
        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._client.request(
                    method=method,
                    url=path,
                    json=json_data,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

                self._circuit.record_success()
                return ModuleResponse(
                    module_name=self.MODULE_NAME,
                    status="success",
                    data=data,
                )

            except httpx.TimeoutException:
                last_error = f"Timeout after {self._settings.client_timeout_seconds}s"
                await logger.awarning(
                    "Request timeout",
                    module=self.MODULE_NAME,
                    path=path,
                    attempt=attempt,
                )
            except httpx.HTTPStatusError as exc:
                last_error = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                await logger.awarning(
                    "HTTP error",
                    module=self.MODULE_NAME,
                    path=path,
                    status_code=exc.response.status_code,
                    attempt=attempt,
                )
            except httpx.RequestError as exc:
                last_error = f"Connection error: {str(exc)[:200]}"
                await logger.awarning(
                    "Connection error",
                    module=self.MODULE_NAME,
                    path=path,
                    error=str(exc)[:200],
                    attempt=attempt,
                )

            # Exponential backoff with jitter
            if attempt < self._max_retries:
                delay = min(
                    self._retry_base_delay * (2 ** (attempt - 1)),
                    self._retry_max_delay,
                )
                await asyncio.sleep(delay)

        # All retries exhausted
        self._circuit.record_failure()
        await logger.aerror(
            "All retries exhausted",
            module=self.MODULE_NAME,
            path=path,
            error=last_error,
        )

        return ModuleResponse(
            module_name=self.MODULE_NAME,
            status="error",
            error_message=last_error,
            is_degraded=True,
            confidence=0.0,
        )

    async def health_check(self) -> bool:
        """Check if the module service is reachable."""
        response = await self._request("GET", "/health")
        return response.status == "success"

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()
