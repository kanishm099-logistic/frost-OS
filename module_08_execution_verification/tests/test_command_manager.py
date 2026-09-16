"""
Unit tests for Command Manager, Idempotency & Resource Locking.
"""

from __future__ import annotations

from app.core.command_manager import CommandManager


def test_command_idempotency(settings):
    mgr = CommandManager(settings)
    key = "IDEMP-KEY-999"

    # First attempt: NEW -> True
    assert mgr.check_idempotency(key) is True
    mgr.mark_idempotency_executed(key)

    # Second attempt: DUPLICATE -> False
    assert mgr.check_idempotency(key) is False


def test_resource_locking_prevents_conflicts(settings):
    mgr = CommandManager(settings)
    res_id = "BAT-01"

    # Plan 1 acquires lock
    acquired, msg = mgr.acquire_resource_lock(res_id, "PLAN-01")
    assert acquired is True

    # Plan 2 attempts lock on same resource -> Fails
    acquired_2, msg_2 = mgr.acquire_resource_lock(res_id, "PLAN-02")
    assert acquired_2 is False
    assert "locked by concurrent plan" in msg_2

    # Plan 1 releases lock
    mgr.release_resource_lock(res_id, "PLAN-01")

    # Plan 2 now acquires lock
    acquired_3, _ = mgr.acquire_resource_lock(res_id, "PLAN-02")
    assert acquired_3 is True
