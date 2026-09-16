"""
Frost OS Module 01 — Redis Streams Constants & Event Types.

Defines stream names, consumer groups, and message schemas for
inter-module communication via Redis Streams.
"""

from __future__ import annotations


# ── Stream Names ──────────────────────────────────────────────────────

class Streams:
    """Redis Stream name constants."""
    EVENTS = "frost.events"
    DECISIONS = "frost.decisions"
    ACTION_PLANS = "frost.action_plans"
    EXECUTION_RESULTS = "frost.execution_results"
    MODULE_STATUS = "frost.module_status"


# ── Consumer Groups ──────────────────────────────────────────────────

class ConsumerGroups:
    """Redis consumer group names."""
    ORCHESTRATOR = "frost-orchestrator-group"
    EXECUTION = "frost-execution-group"


# ── Message Fields ────────────────────────────────────────────────────

class MessageFields:
    """Standard message field names used across all streams."""
    EVENT_ID = "event_id"
    CORRELATION_ID = "correlation_id"
    STATION_ID = "station_id"
    EVENT_TYPE = "event_type"
    SEVERITY = "severity"
    TIMESTAMP = "timestamp"
    SOURCE = "source"
    PAYLOAD = "payload"
    DECISION_ID = "decision_id"
    PLAN_ID = "plan_id"
    STATUS = "status"
    DATA = "data"


# ── Idempotency Key Prefix ───────────────────────────────────────────

PROCESSED_EVENTS_KEY = "frost:processed_events"
