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
    """Return max of two escalation levels where STANDARD < SENIOR < BLOCKED."""
    raise NotImplementedError("T6 stub")


def calculate_policy_level(
    findings: list[Finding],
    cycle_status: str,
    has_eligible_supplier: bool,
    po_total: float | None = None,
    min_confidence: float = 1.0,
    senior_threshold: float = 10000.0,
    low_confidence_threshold: float = 0.60,
) -> Literal["STANDARD", "SENIOR", "BLOCKED"]:
    """Compute deterministic escalation policy floor per SPEC 11."""
    raise NotImplementedError("T6 stub")
