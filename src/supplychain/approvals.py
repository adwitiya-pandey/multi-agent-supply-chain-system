"""Human approval gate and purchase order finalization (approvals.py).

Implements reviewer decision processing, validation, and finalisation of POs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal


class ApprovalError(Exception):
    """Raised when an approval decision violates business or security rules."""


def decide(
    cycle_id: str,
    reviewer: str,
    decision: Literal["APPROVED", "REJECTED"],
    note: str = "",
    db_path: str | Path | None = None,
    audit_path: str | Path | None = None,
) -> dict[str, str]:
    """Process human reviewer decision on a cycle (APPROVED or REJECTED) per SPEC 12."""
    raise NotImplementedError("T6 stub")
