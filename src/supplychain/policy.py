"""Escalation policy rules (policy.py).

Implements deterministic escalation floor calculation and level comparisons.
"""

from __future__ import annotations

from typing import Literal

from supplychain.models import Finding

LEVEL_ORDER = {
    "STANDARD": 0,
    "SENIOR": 1,
    "BLOCKED": 2,
}


def compare_levels(
    level_a: Literal["STANDARD", "SENIOR", "BLOCKED"],
    level_b: Literal["STANDARD", "SENIOR", "BLOCKED"],
) -> Literal["STANDARD", "SENIOR", "BLOCKED"]:
    """Return max of two escalation levels where STANDARD < SENIOR < BLOCKED.

    Ensures the LLM can only raise caution, never lower it.
    """
    if LEVEL_ORDER[level_a] >= LEVEL_ORDER[level_b]:
        return level_a
    return level_b


def calculate_policy_level(
    findings: list[Finding],
    cycle_status: str,
    has_eligible_supplier: bool,
    po_total: float | None = None,
    min_confidence: float = 1.0,
    senior_threshold: float = 10000.0,
    low_confidence_threshold: float = 0.60,
) -> Literal["STANDARD", "SENIOR", "BLOCKED"]:
    """Compute deterministic escalation policy floor per SPEC 11:

    - BLOCKED if status in (FAILED, BUDGET_EXCEEDED), or no eligible supplier, or any CRITICAL finding.
    - SENIOR if PO total >= senior_threshold, or at least 2 WARN findings, or min_confidence < low_confidence,
      or special QA findings QA08, QA10, or QA14 are present.
    - else STANDARD.
    """
    # 1. Blocked conditions
    if cycle_status in ("FAILED", "BUDGET_EXCEEDED"):
        return "BLOCKED"

    if not has_eligible_supplier:
        return "BLOCKED"

    if any(f.severity == "CRITICAL" for f in findings):
        return "BLOCKED"

    # 2. Senior review conditions
    if po_total is not None and round(po_total, 3) >= round(senior_threshold, 3):
        return "SENIOR"

    warn_count = sum(1 for f in findings if f.severity == "WARN")
    if warn_count >= 2:
        return "SENIOR"

    if min_confidence < low_confidence_threshold:
        return "SENIOR"

    special_codes = {"QA08", "QA10", "QA14"}
    if any(f.code in special_codes for f in findings):
        return "SENIOR"

    return "STANDARD"
