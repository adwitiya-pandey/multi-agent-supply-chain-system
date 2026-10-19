"""Tests for append-only audit trail (audit.py)."""

import json
from pathlib import Path

import pytest

from supplychain.audit import AuditError, sha256, write_audit_event


def test_sha256_helper():
    h = sha256("test-payload")
    assert isinstance(h, str)
    assert len(h) == 64
    assert h == sha256(b"test-payload")


def test_write_audit_event_success(tmp_path: Path):
    audit_file = tmp_path / "audit.jsonl"
    cycle_id = "CYC-20261019-0001"

    write_audit_event(
        "cycle_started",
        cycle_id=cycle_id,
        audit_path=audit_file,
        scenario_id="S01",
        sku_id="SKU0001",
    )
    write_audit_event(
        "task_completed",
        cycle_id=cycle_id,
        audit_path=audit_file,
        agent="DemandForecaster",
        sha256=sha256("output"),
    )

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    rec1 = json.loads(lines[0])
    assert rec1["event"] == "cycle_started"
    assert rec1["cycle_id"] == cycle_id
    assert rec1["scenario_id"] == "S01"
    assert "ts" in rec1

    rec2 = json.loads(lines[1])
    assert rec2["event"] == "task_completed"
    assert rec2["agent"] == "DemandForecaster"


def test_audit_rejects_payload_fields(tmp_path: Path):
    audit_file = tmp_path / "audit.jsonl"
    with pytest.raises(ValueError, match="forbidden"):
        write_audit_event(
            "cycle_started",
            cycle_id="CYC-20261019-0001",
            audit_path=audit_file,
            payload="malicious or bulky content",
        )


def test_audit_unknown_event(tmp_path: Path):
    audit_file = tmp_path / "audit.jsonl"
    with pytest.raises(ValueError, match="Unknown audit event"):
        write_audit_event(
            "nonexistent_event",
            cycle_id="CYC-20261019-0001",
            audit_path=audit_file,
        )


def test_audit_write_failure_raises_audit_error(tmp_path: Path):
    # Pass a path that cannot be written (e.g. path is a directory)
    bad_path = tmp_path / "a_directory"
    bad_path.mkdir()

    with pytest.raises(AuditError):
        write_audit_event(
            "cycle_started",
            cycle_id="CYC-20261019-0001",
            audit_path=bad_path,
        )
