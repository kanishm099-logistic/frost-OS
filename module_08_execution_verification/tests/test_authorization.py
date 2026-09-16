"""
Unit tests for Authorization & M07 Safety Checker.
"""

from __future__ import annotations

from app.core.authorization_checker import AuthorizationChecker
from app.models.execution import ActionPlanModel, ActionItemModel, ActionTypeEnum


def test_missing_authorization_rejected(settings, sample_action_plan):
    checker = AuthorizationChecker(settings)
    sample_action_plan.authorization_id = "UNAUTHORIZED"

    authorized, reason = checker.verify_plan_authorization(sample_action_plan)
    assert authorized is False
    assert "Missing valid Module 01 authorization" in reason


def test_unsafe_m07_status_rejected(settings, sample_action_plan):
    checker = AuthorizationChecker(settings)
    sample_action_plan.status = "UNSAFE"

    authorized, reason = checker.verify_plan_authorization(sample_action_plan)
    assert authorized is False
    assert "Module 07 safety status is 'UNSAFE'" in reason


def test_valid_authorization_approved(settings, sample_action_plan):
    checker = AuthorizationChecker(settings)
    authorized, reason = checker.verify_plan_authorization(sample_action_plan)
    assert authorized is True
