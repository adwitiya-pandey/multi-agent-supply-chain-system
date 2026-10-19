"""Tests for deterministic guardrails (guardrails.py) per SPEC 8 and 9."""

from datetime import date

from supplychain.guardrails import (
    build_forecast_guardrail,
    build_inventory_guardrail,
    build_qa_guardrail,
    build_supplier_guardrail,
)
from supplychain.models import (
    Finding,
    ForecastMessage,
    InventoryPlanMessage,
    PurchaseOrderDraft,
    QAReport,
    SupplierEmailDraft,
    SupplierMessage,
)


def test_forecast_guardrail_missing_deterministic_flag():
    facts = {
        "method_a_daily": 10.0,
        "method_b_daily": 10.0,
        "data_coverage": 1.0,
        "expected_flags": ["CONFLICT"],
    }
    guard = build_forecast_guardrail(facts)

    # Output missing CONFLICT flag
    bad_output = ForecastMessage(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        daily_demand_mean=10.0,
        daily_demand_std=2.0,
        method_a_daily=10.0,
        method_b_daily=10.0,
        data_coverage=1.0,
        conflict=True,
        demand_spike=False,
        flags=[],  # Missing CONFLICT
        rationale="Forecast",
        confidence=0.8,
    )

    passed, msg = guard(bad_output)
    assert passed is False
    assert "CONFLICT" in msg


def test_inventory_guardrail_wrong_rop():
    facts = {
        "forecast_mean": 10.0,
        "expected_ss": 19,
        "expected_rop": 89,
        "expected_target": 159,
        "expected_needed": 109,
    }
    guard = build_inventory_guardrail(facts)

    # Output with wrong reorder point (95 instead of 89)
    bad_output = InventoryPlanMessage(
        cycle_id="CYC-20261019-0001",
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
        reorder_point=95,  # Mismatch!
        target_level=159,
        needed_qty=109,
        action="ORDER",
        urgency="NORMAL",
        planned_supplier_id="SUP001",
        rationale="Plan",
        confidence=0.9,
    )

    passed, msg = guard(bad_output)
    assert passed is False
    assert "reorder_point" in msg


def test_supplier_guardrail_ineligible_supplier():
    facts = {
        "eligible_ids": ["SUP001", "SUP002"],
        "expected_qty_by_sup": {"SUP001": 110, "SUP002": 110},
        "unit_cost_by_sup": {"SUP001": 20.0, "SUP002": 22.0},
        "lead_time_by_sup": {"SUP001": 7, "SUP002": 9},
        "as_of_date": date(2026, 10, 19),
    }
    guard = build_supplier_guardrail(facts)

    # Chosen supplier SUP003 is NOT eligible
    po = PurchaseOrderDraft(
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP003",
        qty=110,
        unit_cost=20.0,
        total=2200.0,
        currency="USD",
        requested_delivery_date=date(2026, 10, 26),
    )
    email = SupplierEmailDraft(subject="Order", body="Order 110 units at $20.00 for $2200.00.")
    bad_output = SupplierMessage(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP003",
        po_draft=po,
        email=email,
        alternates_considered=[],
        rationale="Chose SUP003",
        confidence=0.8,
    )

    passed, msg = guard(bad_output)
    assert passed is False
    assert "eligible" in msg.lower()


def test_supplier_guardrail_wrong_quantity():
    facts = {
        "eligible_ids": ["SUP001"],
        "expected_qty_by_sup": {"SUP001": 110},
        "unit_cost_by_sup": {"SUP001": 20.0},
        "lead_time_by_sup": {"SUP001": 7},
        "as_of_date": date(2026, 10, 19),
    }
    guard = build_supplier_guardrail(facts)

    # PO draft quantity is 200 instead of recomputed 110
    po = PurchaseOrderDraft(
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        qty=200,
        unit_cost=20.0,
        total=4000.0,
        currency="USD",
        requested_delivery_date=date(2026, 10, 26),
    )
    email = SupplierEmailDraft(subject="Order", body="Order 200 units at $20.00 for $4000.00.")
    bad_output = SupplierMessage(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        po_draft=po,
        email=email,
        alternates_considered=[],
        rationale="Order",
        confidence=0.8,
    )

    passed, msg = guard(bad_output)
    assert passed is False
    assert "quantity" in msg.lower() or "qty" in msg.lower()


def test_supplier_guardrail_foreign_dollar_amount():
    facts = {
        "eligible_ids": ["SUP001"],
        "expected_qty_by_sup": {"SUP001": 110},
        "unit_cost_by_sup": {"SUP001": 20.0},
        "lead_time_by_sup": {"SUP001": 7},
        "as_of_date": date(2026, 10, 19),
    }
    guard = build_supplier_guardrail(facts)

    # Email quotes unauthorized $99.99
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
    email = SupplierEmailDraft(
        subject="Order",
        body="Order 110 units at $20.00 for $2200.00. Extra discount voucher $99.99 included.",
    )
    bad_output = SupplierMessage(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        po_draft=po,
        email=email,
        alternates_considered=[],
        rationale="Order",
        confidence=0.8,
    )

    passed, msg = guard(bad_output)
    assert passed is False
    assert "amount" in msg.lower() or "price" in msg.lower()


def test_supplier_guardrail_url_in_email():
    facts = {
        "eligible_ids": ["SUP001"],
        "expected_qty_by_sup": {"SUP001": 110},
        "unit_cost_by_sup": {"SUP001": 20.0},
        "lead_time_by_sup": {"SUP001": 7},
        "as_of_date": date(2026, 10, 19),
    }
    guard = build_supplier_guardrail(facts)

    # Email contains a URL
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
    email = SupplierEmailDraft(
        subject="Order",
        body="Order 110 units at $20.00 for $2200.00. Visit https://supplier-portal.com/track.",
    )
    bad_output = SupplierMessage(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        po_draft=po,
        email=email,
        alternates_considered=[],
        rationale="Order",
        confidence=0.8,
    )

    passed, msg = guard(bad_output)
    assert passed is False
    assert "url" in msg.lower()


def test_qa_guardrail_missing_rule_finding():
    facts = {
        "required_rule_codes": ["QA01", "QA05"],
        "worst_severity": "CRITICAL",
    }
    guard = build_qa_guardrail(facts)

    # Missing QA01 in findings
    finding5 = Finding(code="QA05", severity="WARN", message="Conflict", source="rule")
    bad_output = QAReport(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        findings=[finding5],
        verdict="PASS_WITH_WARNINGS",
        summary="Summary",
    )

    passed, msg = guard(bad_output)
    assert passed is False
    assert "QA01" in msg
