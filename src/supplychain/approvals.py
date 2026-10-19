"""Human approval gate and purchase order finalization (approvals.py).

Implements reviewer decision processing, validation, and finalisation of POs.
Sole module authorized to finalize purchase orders.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from supplychain.audit import write_audit_event
from supplychain.sanitize import sanitize_untrusted_text
from supplychain.store import finalise_po, get_cycle, init_app_db

# Strict reviewer name format: starts with letter, 2-40 chars of letters, spaces, dots, apostrophes, hyphens
REVIEWER_NAME_PATTERN = r"^[A-Za-z][A-Za-z .'-]{1,39}$"


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
    if decision not in ("APPROVED", "REJECTED"):
        raise ApprovalError(f"Invalid decision type: {decision!r}")

    # Rule 3: Validate reviewer name format
    if not isinstance(reviewer, str) or not re.fullmatch(REVIEWER_NAME_PATTERN, reviewer):
        raise ApprovalError(
            f"Invalid reviewer name format: {reviewer!r}. Must start with letter and be 2-40 characters."
        )

    # Sanitize note and cap at 500 characters
    sanitized_note, _ = sanitize_untrusted_text(note, max_length=500)

    # Rule 1: Cycle must exist
    result = get_cycle(cycle_id, db_path)
    if not result:
        raise ApprovalError(f"Cycle {cycle_id} not found")

    conn = init_app_db(db_path)
    try:
        # Check if already decided (Rule 1 & Rule 4)
        existing = conn.execute(
            "SELECT decision FROM approvals WHERE cycle_id = ?",
            (cycle_id,),
        ).fetchone()
        if existing:
            raise ApprovalError(f"Cycle {cycle_id} is already decided ({existing['decision']})")

        # Cycle status check (Rule 1)
        if result.status != "PENDING_APPROVAL":
            raise ApprovalError(
                f"Cannot decide on cycle {cycle_id} with status {result.status}. Must be PENDING_APPROVAL."
            )

        # Rule 2: APPROVED is refused when final_level == BLOCKED
        if decision == "APPROVED" and result.final_level == "BLOCKED":
            raise ApprovalError(f"Cannot approve cycle {cycle_id} because final_level is BLOCKED")

        now_iso = datetime.now(UTC).isoformat()
        po_id: str | None = None

        # Begin transaction
        conn.execute("BEGIN IMMEDIATE;")

        # Insert approval decision
        conn.execute(
            """
            INSERT INTO approvals(cycle_id, decision, reviewer, note, decided_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cycle_id, decision, reviewer, sanitized_note, now_iso),
        )

        # Rule 5: On approval, finalise_po copies PO fields from stored CycleResult
        if decision == "APPROVED":
            po_id = finalise_po(conn, result, approved_by=reviewer)

        conn.commit()

        # Rule 6: Write audit lines (fail-closed if audit fails)
        write_audit_event(
            "approval_decided",
            cycle_id=cycle_id,
            decision=decision,
            reviewer=reviewer,
            audit_path=audit_path,
        )
        if po_id:
            write_audit_event(
                "po_finalised",
                cycle_id=cycle_id,
                po_id=po_id,
                audit_path=audit_path,
            )

        out = {
            "cycle_id": cycle_id,
            "decision": decision,
            "reviewer": reviewer,
        }
        if po_id:
            out["po_id"] = po_id
        return out
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
