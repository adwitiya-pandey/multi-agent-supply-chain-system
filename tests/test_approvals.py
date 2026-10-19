"""Tests for the human approval gate (approvals.py)."""

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from supplychain.approvals import ApprovalError, decide
from supplychain.models import (
    CostReport,
    CycleRequest,
    CycleResult,
    ForecastMessage,
    InventoryPlanMessage,
    PurchaseOrderDraft,
    SupplierEmailDraft,
    SupplierMessage,
)
from supplychain.store import init_app_db, save_cycle


def _create_cycle_in_db(
    db_file: Path,
    cycle_id: str = "CYC-20261019-0001",
    status: str = "PENDING_APPROVAL",
    final_level: str = "STANDARD",
    qty: int = 110,
    unit_cost: float = 20.0,
):
    req = CycleRequest(scenario_id="S01", sku_id="SKU0001", warehouse_id="WH-N")
    fc = ForecastMessage(
        cycle_id=cycle_id,
        sku_id="SKU0001",
        warehouse_id="WH-N",
        daily_demand_mean=10.0,
        daily_demand_std=2.0,
        method_a_daily=10.0,
        method_b_daily=10.0,
        data_coverage=1.0,
        conflict=False,
        demand_spike=False,
        flags=[],
        rationale="Steady",
        confidence=0.9,
    )
    plan = InventoryPlanMessage(
        cycle_id=cycle_id,
        sku_id="SKU0001",
        warehouse_id="WH-N",
        on_hand=50,
        on_order=0,
        daily_demand=10.0,
        daily_demand_std=2.0,
        lead_time_days=7,
        lead_time_std=1.0,
        service_level=0.95,
        safety_stock=19,
        reorder_point=89,
        target_level=159,
        needed_qty=109,
        action="ORDER" if qty > 0 else "NO_ACTION",
        urgency="NORMAL",
        planned_supplier_id="SUP001",
        rationale="Order needed",
        confidence=0.9,
    )
    po = PurchaseOrderDraft(
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        qty=qty,
        unit_cost=unit_cost,
        total=qty * unit_cost,
        currency="USD",
        requested_delivery_date=date(2026, 10, 26),
    )
    email = SupplierEmailDraft(subject="Order", body="Please confirm order.")
    sup = SupplierMessage(
        cycle_id=cycle_id,
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        po_draft=po,
        email=email,
        alternates_considered=["SUP002"],
        rationale="Selected SUP001",
        confidence=0.9,
    )
    res = CycleResult(
        cycle_id=cycle_id,
        request=req,
        status=status,
        forecast=fc,
        plan=plan,
        supplier=sup,
        policy_level=final_level,
        final_level=final_level,
        cost=CostReport(total_usd=0.05, budget_usd=0.50),
        created_at="2026-10-19T12:00:00Z",
    )
    save_cycle(res, db_file)
    return res


def test_rule1_unknown_cycle_raises(tmp_path: Path):
    db_file = tmp_path / "app.db"
    init_app_db(db_file)
    with pytest.raises(ApprovalError, match="not found"):
        decide(
            "CYC-20261019-9999",
            reviewer="Alice Smith",
            decision="APPROVED",
            db_path=db_file,
        )


def test_rule1_not_pending_cycle_raises(tmp_path: Path):
    db_file = tmp_path / "app.db"
    _create_cycle_in_db(db_file, "CYC-20261019-0001", status="FAILED", final_level="BLOCKED")
    with pytest.raises(ApprovalError, match="status"):
        decide(
            "CYC-20261019-0001",
            reviewer="Alice Smith",
            decision="APPROVED",
            db_path=db_file,
        )


def test_rule2_approve_refused_when_blocked(tmp_path: Path):
    db_file = tmp_path / "app.db"
    # Cycle has status PENDING_APPROVAL but final_level BLOCKED
    _create_cycle_in_db(
        db_file, "CYC-20261019-0001", status="PENDING_APPROVAL", final_level="BLOCKED"
    )

    # Approving BLOCKED cycle is refused
    with pytest.raises(ApprovalError, match="BLOCKED"):
        decide(
            "CYC-20261019-0001",
            reviewer="Alice Smith",
            decision="APPROVED",
            db_path=db_file,
        )

    # Rejecting is allowed
    res = decide(
        "CYC-20261019-0001",
        reviewer="Alice Smith",
        decision="REJECTED",
        db_path=db_file,
    )
    assert res["decision"] == "REJECTED"


@pytest.mark.parametrize(
    "bad_name",
    [
        "123John",
        "A",  # too short
        "Alice@Smith",
        "John_Doe",
        " " * 10,
        "A" * 50,  # too long
    ],
)
def test_rule3_reviewer_name_validation(tmp_path: Path, bad_name):
    db_file = tmp_path / "app.db"
    _create_cycle_in_db(db_file, "CYC-20261019-0001")
    with pytest.raises((ApprovalError, ValueError)):
        decide(
            "CYC-20261019-0001",
            reviewer=bad_name,
            decision="APPROVED",
            db_path=db_file,
        )


def test_rule4_second_decision_raises(tmp_path: Path):
    db_file = tmp_path / "app.db"
    _create_cycle_in_db(db_file, "CYC-20261019-0001")

    # First decision succeeds
    decide(
        "CYC-20261019-0001",
        reviewer="Alice Smith",
        decision="APPROVED",
        db_path=db_file,
    )

    # Second decision raises
    with pytest.raises(ApprovalError, match="already decided"):
        decide(
            "CYC-20261019-0001",
            reviewer="Bob Jones",
            decision="APPROVED",
            db_path=db_file,
        )


def test_rule5_po_copied_from_stored_result(tmp_path: Path):
    db_file = tmp_path / "app.db"
    _create_cycle_in_db(db_file, "CYC-20261019-0001", qty=110, unit_cost=20.0)

    # Approve
    dec_info = decide(
        "CYC-20261019-0001",
        reviewer="Alice Smith",
        decision="APPROVED",
        db_path=db_file,
    )
    assert dec_info["decision"] == "APPROVED"
    assert "po_id" in dec_info

    # Inspect stored PO
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE cycle_id = 'CYC-20261019-0001'"
    ).fetchone()
    assert row is not None
    assert row["qty"] == 110
    assert row["unit_cost"] == 20.0
    assert row["total"] == 2200.0
    assert row["approved_by"] == "Alice Smith"
    conn.close()


def test_rule6_audit_lines_written(tmp_path: Path):
    db_file = tmp_path / "app.db"
    audit_file = tmp_path / "audit.jsonl"
    _create_cycle_in_db(db_file, "CYC-20261019-0001", qty=110, unit_cost=20.0)

    decide(
        "CYC-20261019-0001",
        reviewer="Alice Smith",
        decision="APPROVED",
        db_path=db_file,
        audit_path=audit_file,
    )

    lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert "approval_decided" in events
    assert "po_finalised" in events
