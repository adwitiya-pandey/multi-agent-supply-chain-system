"""Tests for escalation policy rules (policy.py)."""

import pytest

from supplychain.models import Finding
from supplychain.policy import calculate_policy_level, compare_levels


def test_compare_levels_max_ordering():
    # STANDARD < SENIOR < BLOCKED
    assert compare_levels("STANDARD", "STANDARD") == "STANDARD"
    assert compare_levels("STANDARD", "SENIOR") == "SENIOR"
    assert compare_levels("SENIOR", "STANDARD") == "SENIOR"
    assert compare_levels("SENIOR", "BLOCKED") == "BLOCKED"
    assert compare_levels("BLOCKED", "SENIOR") == "BLOCKED"
    assert compare_levels("BLOCKED", "STANDARD") == "BLOCKED"
    assert compare_levels("STANDARD", "BLOCKED") == "BLOCKED"


def test_policy_blocked_on_cycle_status():
    assert (
        calculate_policy_level(findings=[], cycle_status="FAILED", has_eligible_supplier=True)
        == "BLOCKED"
    )
    assert (
        calculate_policy_level(
            findings=[], cycle_status="BUDGET_EXCEEDED", has_eligible_supplier=True
        )
        == "BLOCKED"
    )


def test_policy_blocked_on_no_eligible_supplier():
    assert (
        calculate_policy_level(
            findings=[], cycle_status="PENDING_APPROVAL", has_eligible_supplier=False
        )
        == "BLOCKED"
    )


def test_policy_blocked_on_critical_finding():
    critical_f = Finding(code="QA01", severity="CRITICAL", message="Mismatched IDs", source="rule")
    assert (
        calculate_policy_level(
            findings=[critical_f], cycle_status="PENDING_APPROVAL", has_eligible_supplier=True
        )
        == "BLOCKED"
    )


def test_policy_senior_on_po_threshold_boundary():
    # Exactly at threshold 10,000 USD
    assert (
        calculate_policy_level(
            findings=[],
            cycle_status="PENDING_APPROVAL",
            has_eligible_supplier=True,
            po_total=10000.0,
            senior_threshold=10000.0,
        )
        == "SENIOR"
    )
    # Just below threshold 9999.99 USD
    assert (
        calculate_policy_level(
            findings=[],
            cycle_status="PENDING_APPROVAL",
            has_eligible_supplier=True,
            po_total=9999.99,
            senior_threshold=10000.0,
        )
        == "STANDARD"
    )


def test_policy_senior_on_two_warn_findings_boundary():
    warn1 = Finding(code="QA05", severity="WARN", message="Conflict", source="rule")
    warn2 = Finding(code="QA06", severity="WARN", message="Spike", source="rule")

    # Exactly 2 WARN findings -> SENIOR
    assert (
        calculate_policy_level(
            findings=[warn1, warn2],
            cycle_status="PENDING_APPROVAL",
            has_eligible_supplier=True,
        )
        == "SENIOR"
    )
    # Exactly 1 WARN finding (not QA08/QA10/QA14) -> STANDARD
    assert (
        calculate_policy_level(
            findings=[warn1],
            cycle_status="PENDING_APPROVAL",
            has_eligible_supplier=True,
        )
        == "STANDARD"
    )


def test_policy_senior_on_low_confidence_boundary():
    # Confidence strictly below 0.60
    assert (
        calculate_policy_level(
            findings=[],
            cycle_status="PENDING_APPROVAL",
            has_eligible_supplier=True,
            min_confidence=0.599,
            low_confidence_threshold=0.60,
        )
        == "SENIOR"
    )
    # Confidence exactly 0.60 -> STANDARD
    assert (
        calculate_policy_level(
            findings=[],
            cycle_status="PENDING_APPROVAL",
            has_eligible_supplier=True,
            min_confidence=0.60,
            low_confidence_threshold=0.60,
        )
        == "STANDARD"
    )


@pytest.mark.parametrize("special_qa", ["QA08", "QA10", "QA14"])
def test_policy_senior_on_special_qa_findings(special_qa):
    finding = Finding(code=special_qa, severity="WARN", message="Special trigger", source="rule")
    assert (
        calculate_policy_level(
            findings=[finding],
            cycle_status="PENDING_APPROVAL",
            has_eligible_supplier=True,
        )
        == "SENIOR"
    )
