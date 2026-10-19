"""Append-only audit trail logging for all key lifecycle events."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from supplychain.config import get_settings

VALID_AUDIT_EVENTS = {
    "cycle_started",
    "task_completed",
    "guardrail_failed",
    "findings",
    "policy_level",
    "escalation_decided",
    "cycle_finished",
    "approval_decided",
    "po_finalised",
    "cycle_failed",
}


class AuditError(RuntimeError):
    """Raised when an audit line cannot be written (fail-closed requirement)."""


def sha256(data: str | bytes) -> str:
    """Compute SHA-256 hash of string or bytes."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def write_audit_event(
    event: str,
    cycle_id: str,
    audit_path: str | Path | None = None,
    **kwargs: Any,
) -> None:
    """Write an append-only audit event line to audit.jsonl (fail-closed)."""
    if event not in VALID_AUDIT_EVENTS:
        raise ValueError(f"Unknown audit event type: {event}")

    # Build record: ts, event, cycle_id, plus ids and codes only (no payloads)
    now_iso = datetime.now(UTC).isoformat()
    record: dict[str, Any] = {
        "ts": now_iso,
        "event": event,
        "cycle_id": cycle_id,
    }

    # Add extra metadata (e.g. agent, sha256, tokens, codes)
    for k, v in kwargs.items():
        if k in {"payload", "body", "note", "notes", "prompt", "text"}:
            raise ValueError(f"Payload field {k!r} forbidden in audit log")
        record[k] = v

    target_path = Path(audit_path or get_settings().audit_path)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True) + "\n"
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception as exc:
        raise AuditError(f"Failed to append audit event {event} to {target_path}: {exc}") from exc
