"""Tests for app database storage and append-only triggers (store.py)."""

import sqlite3
from datetime import date
from pathlib import Path

import pytest

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
from supplychain.store import (
    finalise_po,
    get_cycle,
    init_app_db,
    list_history,
    list_pending,
    save_cycle,
)


def _make_dummy_cycle_result(cycle_id="CYC-20261019-0001", status="PENDING_APPROVAL"):
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
        action="ORDER",
        urgency="NORMAL",
        planned_supplier_id="SUP001",
        rationale="Order needed",
        confidence=0.9,
    )
    po = PurchaseOrderDraft(
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        qty=110,
        unit_cost=20.0,
        total=2200.0,
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
    cost = CostReport(total_usd=0.05, budget_usd=0.50)
    return CycleResult(
        cycle_id=cycle_id,
        request=req,
        status=status,
        forecast=fc,
        plan=plan,
        supplier=sup,
        policy_level="STANDARD",
        final_level="STANDARD",
        cost=cost,
        created_at="2026-10-19T12:00:00Z",
    )


def test_save_and_get_cycle(tmp_path: Path):
    db_file = tmp_path / "app.db"
    res = _make_dummy_cycle_result("CYC-20261019-0001")
    save_cycle(res, db_file)

    loaded = get_cycle("CYC-20261019-0001", db_file)
    assert loaded is not None
    assert loaded.cycle_id == "CYC-20261019-0001"
    assert loaded.status == "PENDING_APPROVAL"
    assert loaded.supplier.po_draft.qty == 110


def test_list_pending(tmp_path: Path):
    db_file = tmp_path / "app.db"
    res1 = _make_dummy_cycle_result("CYC-20261019-0001", status="PENDING_APPROVAL")
    res2 = _make_dummy_cycle_result("CYC-20261019-0002", status="BLOCKED")
    save_cycle(res1, db_file)
    save_cycle(res2, db_file)

    pending = list_pending(db_file)
    assert len(pending) == 1
    assert pending[0].cycle_id == "CYC-20261019-0001"


def test_cycles_triggers_reject_update_and_delete(tmp_path: Path):
    db_file = tmp_path / "app.db"
    res = _make_dummy_cycle_result("CYC-20261019-0001")
    save_cycle(res, db_file)

    conn = init_app_db(db_file)
    # UPDATE on cycles must fail (trigger abort)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE cycles SET status = 'BLOCKED' WHERE cycle_id = 'CYC-20261019-0001'")

    # DELETE on cycles must fail (trigger abort)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM cycles WHERE cycle_id = 'CYC-20261019-0001'")

    conn.close()


def test_approvals_triggers_reject_update_and_delete(tmp_path: Path):
    db_file = tmp_path / "app.db"
    conn = init_app_db(db_file)
    conn.execute(
        "INSERT INTO approvals VALUES ('CYC-20261019-0001', 'APPROVED', 'Alice Smith', 'Looks good', '2026-10-19T12:00:00Z')"
    )
    conn.commit()

    # UPDATE on approvals must fail
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute(
            "UPDATE approvals SET decision = 'REJECTED' WHERE cycle_id = 'CYC-20261019-0001'"
        )

    # DELETE on approvals must fail
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM approvals WHERE cycle_id = 'CYC-20261019-0001'")

    conn.close()


def test_purchase_orders_triggers_reject_update_and_delete(tmp_path: Path):
    db_file = tmp_path / "app.db"
    conn = init_app_db(db_file)
    res = _make_dummy_cycle_result("CYC-20261019-0001")
    po_id = finalise_po(conn, res, approved_by="Alice Smith")
    conn.commit()

    # UPDATE on purchase_orders must fail
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("UPDATE purchase_orders SET qty = 999 WHERE po_id = ?", (po_id,))

    # DELETE on purchase_orders must fail
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute("DELETE FROM purchase_orders WHERE po_id = ?", (po_id,))

    conn.close()


def test_history_listing(tmp_path: Path):
    db_file = tmp_path / "app.db"
    res = _make_dummy_cycle_result("CYC-20261019-0001")
    save_cycle(res, db_file)
    conn = init_app_db(db_file)
    conn.execute(
        "INSERT INTO approvals VALUES ('CYC-20261019-0001', 'APPROVED', 'Alice Smith', 'Note', '2026-10-19T12:00:00Z')"
    )
    finalise_po(conn, res, approved_by="Alice Smith")
    conn.commit()
    conn.close()

    history = list_history(db_file)
    assert len(history) == 1
    assert history[0]["cycle_id"] == "CYC-20261019-0001"
    assert history[0]["decision"] == "APPROVED"
    assert history[0]["reviewer"] == "Alice Smith"
    assert history[0]["po_total"] == 2200.0
