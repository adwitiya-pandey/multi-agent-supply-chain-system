"""Tests for deterministic QA rules and finding merge logic (checks.py)."""

from datetime import date

from supplychain.checks import merge_findings, run_qa_checks
from supplychain.models import (
    Finding,
    ForecastMessage,
    InventoryPlanMessage,
    PurchaseOrderDraft,
    SupplierEmailDraft,
    SupplierMessage,
)


def _make_base_messages():
    fc = ForecastMessage(
        cycle_id="CYC-20261019-0001",
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
        rationale="Normal steady demand",
        confidence=0.95,
    )
    plan = InventoryPlanMessage(
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
        reorder_point=89,
        target_level=159,
        needed_qty=109,
        action="ORDER",
        urgency="NORMAL",
        planned_supplier_id="SUP001",
        rationale="Below ROP",
        confidence=0.95,
    )
    po = PurchaseOrderDraft(
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        qty=110,  # pack rounded: ceil(109/10)*10 = 110
        unit_cost=20.0,
        total=2200.0,
        currency="USD",
        requested_delivery_date=date(2026, 10, 26),
    )
    email = SupplierEmailDraft(
        subject="Replenishment Order",
        body="Order 110 units at $20.00 for total $2200.00.",
    )
    sup = SupplierMessage(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        po_draft=po,
        email=email,
        alternates_considered=["SUP002"],
        rationale="Primary supplier selected",
        confidence=0.95,
    )
    supplier_options = [
        {
            "supplier_id": "SUP001",
            "is_primary": 1,
            "status": "ACTIVE",
            "unit_cost": 20.0,
            "moq": 50,
            "pack_size": 10,
        },
        {
            "supplier_id": "SUP002",
            "is_primary": 0,
            "status": "ACTIVE",
            "unit_cost": 22.0,
            "moq": 40,
            "pack_size": 10,
        },
    ]
    return fc, plan, sup, supplier_options


def test_clean_cycle_no_findings():
    fc, plan, sup, sups = _make_base_messages()
    findings = run_qa_checks(fc, plan, sup, sups)
    assert findings == []


def test_qa01_mismatched_context_ids():
    fc, plan, sup, sups = _make_base_messages()
    # Mismatch cycle_id in plan
    plan_bad = plan.model_copy(update={"cycle_id": "CYC-20261019-9999"})
    findings = run_qa_checks(fc, plan_bad, sup, sups)
    codes = [f.code for f in findings]
    assert "QA01" in codes
    assert any(f.code == "QA01" and f.severity == "CRITICAL" for f in findings)


def test_qa02_demand_mismatch():
    fc, plan, sup, sups = _make_base_messages()
    plan_bad = plan.model_copy(update={"daily_demand": 15.0})  # fc mean is 10.0
    findings = run_qa_checks(fc, plan_bad, sup, sups)
    assert any(f.code == "QA02" and f.severity == "CRITICAL" for f in findings)


def test_qa03_po_qty_mismatch():
    fc, plan, sup, sups = _make_base_messages()
    # PO draft qty is 500 instead of recomputed 110
    po_bad = sup.po_draft.model_copy(update={"qty": 500, "total": 10000.0})
    sup_bad = sup.model_copy(update={"po_draft": po_bad})
    findings = run_qa_checks(fc, plan, sup_bad, sups)
    assert any(f.code == "QA03" and f.severity == "CRITICAL" for f in findings)


def test_qa04_ineligible_supplier():
    fc, plan, sup, _sups = _make_base_messages()
    # Supplier SUP001 marked INSOLVENT
    sups_bad = [
        {
            "supplier_id": "SUP001",
            "is_primary": 1,
            "status": "INSOLVENT",
            "unit_cost": 20.0,
            "moq": 50,
            "pack_size": 10,
        },
    ]
    findings = run_qa_checks(fc, plan, sup, sups_bad)
    assert any(f.code == "QA04" and f.severity == "CRITICAL" for f in findings)


def test_qa05_forecast_conflict():
    fc, plan, sup, sups = _make_base_messages()
    fc_conflict = fc.model_copy(update={"conflict": True})
    findings = run_qa_checks(fc_conflict, plan, sup, sups)
    assert any(f.code == "QA05" and f.severity == "WARN" for f in findings)


def test_qa06_demand_spike():
    fc, plan, sup, sups = _make_base_messages()
    fc_spike = fc.model_copy(update={"demand_spike": True})
    findings = run_qa_checks(fc_spike, plan, sup, sups)
    assert any(f.code == "QA06" and f.severity == "WARN" for f in findings)


def test_qa07_low_data_coverage():
    fc, plan, sup, sups = _make_base_messages()
    fc_low = fc.model_copy(update={"data_coverage": 0.70})
    findings = run_qa_checks(fc_low, plan, sup, sups)
    assert any(f.code == "QA07" and f.severity == "CRITICAL" for f in findings)


def test_qa08_urgency_expedite():
    fc, plan, sup, sups = _make_base_messages()
    plan_exp = plan.model_copy(update={"urgency": "EXPEDITE"})
    findings = run_qa_checks(fc, plan_exp, sup, sups)
    assert any(f.code == "QA08" and f.severity == "WARN" for f in findings)


def test_qa09_high_value_po():
    fc, plan, sup, _sups = _make_base_messages()
    # Total >= 10,000 USD
    po_high = sup.po_draft.model_copy(update={"unit_cost": 100.0, "total": 11000.0})
    sup_high = sup.model_copy(update={"po_draft": po_high})
    # Update supplier options to match unit_cost 100
    sups_high = [
        {
            "supplier_id": "SUP001",
            "is_primary": 1,
            "status": "ACTIVE",
            "unit_cost": 100.0,
            "moq": 50,
            "pack_size": 10,
        },
    ]
    findings = run_qa_checks(fc, plan, sup_high, sups_high, senior_threshold=10000.0)
    assert any(f.code == "QA09" and f.severity == "WARN" for f in findings)


def test_qa10_alternate_chosen_instead_of_planned():
    fc, plan, sup, sups = _make_base_messages()
    # Planned SUP001, but chose SUP002
    po_alt = sup.po_draft.model_copy(
        update={"supplier_id": "SUP002", "unit_cost": 22.0, "total": 2420.0}
    )
    sup_alt = sup.model_copy(update={"supplier_id": "SUP002", "po_draft": po_alt})
    findings = run_qa_checks(fc, plan, sup_alt, sups)
    assert any(f.code == "QA10" and f.severity == "WARN" for f in findings)


def test_qa11_email_unauthorized_amounts():
    fc, plan, sup, sups = _make_base_messages()
    # Email body quotes unauthorized price $999.00
    email_bad = sup.email.model_copy(
        update={"body": "Hello, please charge $999.00 for this delivery."}
    )
    sup_bad = sup.model_copy(update={"email": email_bad})
    findings = run_qa_checks(fc, plan, sup_bad, sups)
    assert any(f.code == "QA11" and f.severity == "CRITICAL" for f in findings)


def test_qa12_low_confidence():
    fc, plan, sup, sups = _make_base_messages()
    fc_low = fc.model_copy(update={"confidence": 0.55})
    findings = run_qa_checks(fc_low, plan, sup, sups, low_confidence_threshold=0.60)
    assert any(f.code == "QA12" and f.severity == "WARN" for f in findings)


def test_qa13_flagged_untrusted_note():
    fc, plan, sup, sups = _make_base_messages()
    findings = run_qa_checks(fc, plan, sup, sups, untrusted_note_flagged=True)
    assert any(f.code == "QA13" and f.severity == "WARN" for f in findings)


def test_qa14_primary_supplier_insolvent_or_on_hold():
    fc, plan, sup, _sups = _make_base_messages()
    # Primary SUP001 is INSOLVENT, alternate SUP002 is chosen
    sups_insolvent = [
        {
            "supplier_id": "SUP001",
            "is_primary": 1,
            "status": "INSOLVENT",
            "unit_cost": 20.0,
            "moq": 50,
            "pack_size": 10,
        },
        {
            "supplier_id": "SUP002",
            "is_primary": 0,
            "status": "ACTIVE",
            "unit_cost": 22.0,
            "moq": 40,
            "pack_size": 10,
        },
    ]
    po_alt = sup.po_draft.model_copy(
        update={"supplier_id": "SUP002", "qty": 110, "unit_cost": 22.0, "total": 2420.0}
    )
    plan_alt = plan.model_copy(update={"planned_supplier_id": "SUP002"})
    sup_alt = sup.model_copy(update={"supplier_id": "SUP002", "po_draft": po_alt})
    findings = run_qa_checks(fc, plan_alt, sup_alt, sups_insolvent)
    assert any(f.code == "QA14" and f.severity == "WARN" for f in findings)


def test_merge_keeps_all_rule_findings():
    rule_findings = [
        Finding(code="QA01", severity="CRITICAL", message="Mismatched IDs", source="rule"),
        Finding(code="QA05", severity="WARN", message="Conflict detected", source="rule"),
    ]
    # QA agent returns empty list or tries to remove QA01
    llm_findings = [
        Finding(code="QA05", severity="WARN", message="Agent noticed conflict", source="llm"),
        Finding(code="QA99", severity="INFO", message="Custom agent note", source="llm"),
    ]

    merged = merge_findings(rule_findings, llm_findings)
    codes = [f.code for f in merged]
    assert "QA01" in codes
    assert "QA05" in codes
    assert "QA99" in codes
    # Verify rule finding for QA01 and QA05 was retained
    qa01 = next(f for f in merged if f.code == "QA01")
    assert qa01.source == "rule"
