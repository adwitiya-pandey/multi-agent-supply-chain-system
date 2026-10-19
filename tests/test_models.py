"""Tests for Pydantic message contracts (models.py)."""

from datetime import date

import pytest
from pydantic import ValidationError

from supplychain.models import (
    CycleRequest,
    EscalationDecision,
    Finding,
    ForecastMessage,
    InventoryPlanMessage,
    PurchaseOrderDraft,
    QAReport,
    SupplierEmailDraft,
    SupplierMessage,
    round_floats,
)


def test_cycle_request_valid():
    req = CycleRequest(scenario_id="S01", sku_id="SKU0001", warehouse_id="WH-N")
    assert req.sku_id == "SKU0001"
    assert req.warehouse_id == "WH-N"


@pytest.mark.parametrize(
    "bad_sku",
    [
        "SKU0001\n",  # trailing newline
        "sku0001",  # lowercase
        "SKU001",  # 3 digits
        "SKU00001",  # 5 digits
        "SKU٠٠٠١",  # non-ASCII digits
        "SKUABCD",
    ],
)
def test_cycle_request_bad_sku(bad_sku):
    with pytest.raises(ValidationError):
        CycleRequest(scenario_id="S01", sku_id=bad_sku, warehouse_id="WH-N")


@pytest.mark.parametrize(
    "bad_wh",
    ["WH-N\n", "WH-E", "wh-n", "WH-NORTH"],
)
def test_cycle_request_bad_warehouse(bad_wh):
    with pytest.raises(ValidationError):
        CycleRequest(scenario_id="S01", sku_id="SKU0001", warehouse_id=bad_wh)


def test_cycle_request_extra_field():
    with pytest.raises(ValidationError):
        CycleRequest(
            scenario_id="S01",
            sku_id="SKU0001",
            warehouse_id="WH-N",
            unexpected_field="disallowed",
        )


def test_forecast_message_valid():
    fc = ForecastMessage(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        daily_demand_mean=10.5,
        daily_demand_std=2.1,
        method_a_daily=10.0,
        method_b_daily=11.0,
        data_coverage=0.95,
        conflict=False,
        demand_spike=False,
        flags=["PROMO_ACTIVE"],
        rationale="Seasonal baseline demand steady.",
        confidence=0.9,
    )
    assert fc.horizon_days == 14
    assert fc.daily_demand_mean == 10.5


def test_forecast_message_invalid_cycle_id():
    with pytest.raises(ValidationError):
        ForecastMessage(
            cycle_id="CYC-20261019-0001\n",
            sku_id="SKU0001",
            warehouse_id="WH-N",
            daily_demand_mean=10.5,
            daily_demand_std=2.1,
            method_a_daily=10.0,
            method_b_daily=11.0,
            data_coverage=0.95,
            conflict=False,
            demand_spike=False,
            flags=[],
            rationale="Valid rationale",
            confidence=0.8,
        )


def test_forecast_message_bounds_violation():
    with pytest.raises(ValidationError):
        ForecastMessage(
            cycle_id="CYC-20261019-0001",
            sku_id="SKU0001",
            warehouse_id="WH-N",
            daily_demand_mean=-1.0,  # ge=0 violation
            daily_demand_std=2.1,
            method_a_daily=10.0,
            method_b_daily=11.0,
            data_coverage=1.5,  # le=1.0 violation
            conflict=False,
            demand_spike=False,
            flags=[],
            rationale="Rationale",
            confidence=1.2,  # le=1.0 violation
        )


def test_inventory_plan_valid():
    plan = InventoryPlanMessage(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        on_hand=50,
        on_order=0,
        daily_demand=10.0,
        daily_demand_std=2.0,
        lead_time_days=5,
        lead_time_std=1.0,
        service_level=0.95,
        safety_stock=15,
        reorder_point=65,
        target_level=135,
        needed_qty=85,
        action="ORDER",
        urgency="NORMAL",
        planned_supplier_id="SUP001",
        rationale="Position below ROP",
        confidence=0.95,
    )
    assert plan.needed_qty == 85


def test_inventory_plan_bad_supplier_id():
    with pytest.raises(ValidationError):
        InventoryPlanMessage(
            cycle_id="CYC-20261019-0001",
            sku_id="SKU0001",
            warehouse_id="WH-N",
            on_hand=50,
            on_order=0,
            daily_demand=10.0,
            daily_demand_std=2.0,
            lead_time_days=5,
            lead_time_std=1.0,
            service_level=0.95,
            safety_stock=15,
            reorder_point=65,
            target_level=135,
            needed_qty=85,
            action="ORDER",
            urgency="NORMAL",
            planned_supplier_id="SUP01\n",  # invalid format
            rationale="Position below ROP",
            confidence=0.95,
        )


def test_supplier_message_order_requires_drafts():
    po = PurchaseOrderDraft(
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        qty=100,
        unit_cost=12.5,
        total=1250.0,
        currency="USD",
        requested_delivery_date=date(2026, 11, 1),
    )
    email = SupplierEmailDraft(
        subject="Replenishment Order PO-001",
        body="Please confirm order of 100 units.",
    )

    # Valid order with all three
    msg = SupplierMessage(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        supplier_id="SUP001",
        po_draft=po,
        email=email,
        alternates_considered=["SUP002"],
        rationale="Primary supplier selected.",
        confidence=0.9,
    )
    assert msg.supplier_id == "SUP001"

    # po_draft without email raises
    with pytest.raises(ValidationError):
        SupplierMessage(
            cycle_id="CYC-20261019-0001",
            sku_id="SKU0001",
            warehouse_id="WH-N",
            supplier_id="SUP001",
            po_draft=po,
            email=None,
            rationale="Missing email",
            confidence=0.9,
        )


def test_qa_finding_and_report_valid():
    f = Finding(
        code="QA05",
        severity="WARN",
        message="Forecast methods differ by more than 30%",
        source="rule",
    )
    rep = QAReport(
        cycle_id="CYC-20261019-0001",
        sku_id="SKU0001",
        warehouse_id="WH-N",
        findings=[f],
        verdict="PASS_WITH_WARNINGS",
        summary="Minor forecast variance detected.",
    )
    assert len(rep.findings) == 1
    assert rep.findings[0].code == "QA05"


def test_escalation_decision_reasons_bound():
    # Max 8 reasons allowed
    too_many = [f"Reason {i}" for i in range(9)]
    with pytest.raises(ValidationError):
        EscalationDecision(
            cycle_id="CYC-20261019-0001",
            sku_id="SKU0001",
            warehouse_id="WH-N",
            level="SENIOR",
            reasons=too_many,
            confidence=0.8,
        )


def test_round_floats_helper():
    data = {"a": 1.23456, "b": [2.34567, {"c": 3.45678}]}
    rounded = round_floats(data, 3)
    assert rounded == {"a": 1.235, "b": [2.346, {"c": 3.457}]}
