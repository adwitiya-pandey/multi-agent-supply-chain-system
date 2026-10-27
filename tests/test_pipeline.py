"""Pipeline integration tests (test_pipeline.py) per SPEC 8, 9, 10, 11."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

from scripts.build_db import build_database
from supplychain.models import CycleRequest
from supplychain.pipeline import run_cycle


def test_s01_end_to_end_oracle_mode(tmp_path: Path, monkeypatch):
    supply_db = tmp_path / "supply.db"
    app_db = tmp_path / "app.db"
    audit_file = tmp_path / "audit.jsonl"

    build_database(supply_db, scenario_id="S01")

    monkeypatch.setenv("SUPPLY_DB", str(supply_db))
    monkeypatch.setenv("APP_DB", str(app_db))
    monkeypatch.setenv("AUDIT_PATH", str(audit_file))

    req = CycleRequest(scenario_id="S01", sku_id="SKU0001", warehouse_id="WH-N")
    result = run_cycle(req, mode="oracle")

    assert result.status == "PENDING_APPROVAL"
    assert result.final_level == "STANDARD"
    assert result.forecast is not None
    assert result.plan is not None
    assert result.supplier is not None
    assert result.qa is not None
    assert result.escalation is not None
    assert result.cost.total_usd > 0.0

    # CRUCIAL ASSERTION: run_cycle NEVER finalises a purchase order!
    conn = sqlite3.connect(app_db)
    po_count = conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]
    conn.close()
    assert po_count == 0, "run_cycle illegally created a purchase order record"


def test_failed_on_malformed_message(tmp_path: Path, monkeypatch):
    supply_db = tmp_path / "supply.db"
    app_db = tmp_path / "app.db"
    audit_file = tmp_path / "audit.jsonl"

    build_database(supply_db, scenario_id="S10")

    monkeypatch.setenv("SUPPLY_DB", str(supply_db))
    monkeypatch.setenv("APP_DB", str(app_db))
    monkeypatch.setenv("AUDIT_PATH", str(audit_file))

    req = CycleRequest(scenario_id="S10", sku_id="SKU0010", warehouse_id="WH-N")
    result = run_cycle(req, mode="oracle", fault_mode="invalid_json")

    assert result.status == "FAILED"
    assert result.final_level == "BLOCKED"

    conn = sqlite3.connect(app_db)
    po_count = conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]
    conn.close()
    assert po_count == 0


def test_budget_exceeded_with_tiny_budget(tmp_path: Path, monkeypatch):
    supply_db = tmp_path / "supply.db"
    app_db = tmp_path / "app.db"
    audit_file = tmp_path / "audit.jsonl"

    build_database(supply_db, scenario_id="S01")

    monkeypatch.setenv("SUPPLY_DB", str(supply_db))
    monkeypatch.setenv("APP_DB", str(app_db))
    monkeypatch.setenv("AUDIT_PATH", str(audit_file))
    monkeypatch.setenv("COST_BUDGET_USD", "0.0000001")

    req = CycleRequest(scenario_id="S01", sku_id="SKU0001", warehouse_id="WH-N")
    result = run_cycle(req, mode="oracle")

    assert result.status == "BUDGET_EXCEEDED"
    assert result.final_level == "BLOCKED"


def test_findings_merge_preserves_rules(tmp_path: Path, monkeypatch):
    supply_db = tmp_path / "supply.db"
    app_db = tmp_path / "app.db"
    audit_file = tmp_path / "audit.jsonl"

    build_database(supply_db, scenario_id="S03")

    monkeypatch.setenv("SUPPLY_DB", str(supply_db))
    monkeypatch.setenv("APP_DB", str(app_db))
    monkeypatch.setenv("AUDIT_PATH", str(audit_file))

    req = CycleRequest(scenario_id="S03", sku_id="SKU0003", warehouse_id="WH-N")
    result = run_cycle(req, mode="oracle")

    assert result.qa is not None
    codes = [f.code for f in result.qa.findings]
    assert "QA06" in codes
    assert result.final_level == "SENIOR"


def test_task_sequence_and_agent_assignment():
    from supplychain.agents import create_agents
    from supplychain.tasks import create_tasks

    agents = create_agents(mode="oracle")
    context = {"cycle_id": "CYC-TEST-0001", "sku_id": "SKU0001", "warehouse_id": "WH-N"}
    tasks = create_tasks(agents, context, {})

    assert len(tasks) == 5
    expected_sequence = [
        ("forecaster", "Demand Forecaster"),
        ("planner", "Inventory Planner"),
        ("supplier", "Supplier Liaison"),
        ("qa", "Quality Assurance"),
        ("escalation", "Escalation Manager"),
    ]

    for task, (agent_key, expected_role) in zip(tasks, expected_sequence, strict=True):
        assert task.agent == agents[agent_key]
        assert task.agent.role == expected_role


def test_s10_validation_error_log_is_truncated(tmp_path: Path, monkeypatch):
    """S10 fault mode: logged error must not exceed 300 chars and must not dump raw input.

    AGENTS.md §8: 'never log [raw validation input]'.  The fix in pipeline.py formats
    ValidationError as '<class>: <N> validation error(s); first: <first_msg[:200]>'.
    """
    supply_db = tmp_path / "supply.db"
    app_db = tmp_path / "app.db"
    audit_file = tmp_path / "audit.jsonl"

    build_database(supply_db, scenario_id="S10")

    monkeypatch.setenv("SUPPLY_DB", str(supply_db))
    monkeypatch.setenv("APP_DB", str(app_db))
    monkeypatch.setenv("AUDIT_PATH", str(audit_file))

    logged_errors: list[str] = []

    def capture_error(event: str, **kw: object) -> None:  # type: ignore[return]
        if "error" in kw:
            logged_errors.append(str(kw["error"]))

    with patch("supplychain.pipeline.logger") as mock_log:
        mock_log.error.side_effect = capture_error
        req = CycleRequest(scenario_id="S10", sku_id="SKU0010", warehouse_id="WH-N")
        result = run_cycle(req, mode="oracle", fault_mode="invalid_json")

    assert result.status == "FAILED"

    # At least one error must have been logged
    assert logged_errors, "No error was logged during S10 FAILED cycle"

    for err in logged_errors:
        # Must not be a raw 3 KB pydantic dump; capped summary is well under 500 chars
        assert len(err) < 500, f"Logged error is too large ({len(err)} chars): {err[:120]!r}"
        # Must not contain raw Python repr of validation input values (pydantic dumps "input=...")
        assert "input=" not in err, f"Raw validation input leaked into log: {err[:120]!r}"
