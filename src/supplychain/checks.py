"""Deterministic QA consistency rules (checks.py) per SPEC 10."""

from __future__ import annotations

import re
from typing import Any

from supplychain.models import Finding, ForecastMessage, InventoryPlanMessage, SupplierMessage
from supplychain.planning import filter_eligible_suppliers, round_to_supplier_pack


def run_qa_checks(
    forecast: ForecastMessage,
    plan: InventoryPlanMessage,
    supplier: SupplierMessage,
    supplier_options: list[dict[str, Any]],
    senior_threshold: float = 10000.0,
    low_confidence_threshold: float = 0.60,
    untrusted_note_flagged: bool = False,
) -> list[Finding]:
    """Execute deterministic QA rules QA01 through QA14 on the cycle messages."""
    findings: list[Finding] = []

    # QA01: cycle_id, sku_id, warehouse_id differ between any two messages
    contexts = [
        (forecast.cycle_id, forecast.sku_id, forecast.warehouse_id),
        (plan.cycle_id, plan.sku_id, plan.warehouse_id),
        (supplier.cycle_id, supplier.sku_id, supplier.warehouse_id),
    ]
    if len(set(contexts)) > 1:
        findings.append(
            Finding(
                code="QA01",
                severity="CRITICAL",
                message="cycle_id, sku_id, or warehouse_id mismatch between pipeline messages",
                source="rule",
            )
        )

    # QA02: inventory daily_demand != forecast daily_demand_mean
    if round(plan.daily_demand, 3) != round(forecast.daily_demand_mean, 3):
        findings.append(
            Finding(
                code="QA02",
                severity="CRITICAL",
                message=(
                    f"Inventory plan daily demand ({plan.daily_demand:.3f}) does not match "
                    f"forecast mean ({forecast.daily_demand_mean:.3f})"
                ),
                source="rule",
            )
        )

    # Find the chosen supplier record if PO exists
    chosen_sup_record = None
    if supplier.supplier_id:
        chosen_sup_record = next(
            (s for s in supplier_options if s.get("supplier_id") == supplier.supplier_id),
            None,
        )

    # QA03: PO qty != qty recomputed for the chosen supplier
    if supplier.po_draft and chosen_sup_record:
        moq = chosen_sup_record.get("moq", 1)
        pack_size = chosen_sup_record.get("pack_size", 1)
        expected_qty = round_to_supplier_pack(plan.needed_qty, moq=moq, pack_size=pack_size)
        if supplier.po_draft.qty != expected_qty:
            findings.append(
                Finding(
                    code="QA03",
                    severity="CRITICAL",
                    message=(
                        f"PO quantity ({supplier.po_draft.qty}) does not match "
                        f"recomputed requirement ({expected_qty})"
                    ),
                    source="rule",
                )
            )

    # QA04: chosen supplier not eligible
    if supplier.supplier_id:
        eligible_suppliers = filter_eligible_suppliers(supplier_options)
        eligible_ids = {s["supplier_id"] for s in eligible_suppliers}
        if supplier.supplier_id not in eligible_ids:
            findings.append(
                Finding(
                    code="QA04",
                    severity="CRITICAL",
                    message=f"Chosen supplier {supplier.supplier_id} is not eligible",
                    source="rule",
                )
            )

    # QA05: forecast conflict
    if forecast.conflict:
        findings.append(
            Finding(
                code="QA05",
                severity="WARN",
                message="Forecast baseline methods A and B diverge by more than 30%",
                source="rule",
            )
        )

    # QA06: forecast demand spike
    if forecast.demand_spike:
        findings.append(
            Finding(
                code="QA06",
                severity="WARN",
                message="Recent 7-day demand is at least double historical baseline",
                source="rule",
            )
        )

    # QA07: data_coverage < 0.80
    if round(forecast.data_coverage, 3) < 0.80:
        findings.append(
            Finding(
                code="QA07",
                severity="CRITICAL",
                message=f"Data coverage ({forecast.data_coverage:.2%}) is below the required 80% threshold",
                source="rule",
            )
        )

    # QA08: urgency == EXPEDITE
    if plan.urgency == "EXPEDITE":
        findings.append(
            Finding(
                code="QA08",
                severity="WARN",
                message="Inventory position requires expedited procurement",
                source="rule",
            )
        )

    # QA09: PO total >= SENIOR_PO_THRESHOLD_USD
    if supplier.po_draft and round(supplier.po_draft.total, 3) >= round(senior_threshold, 3):
        findings.append(
            Finding(
                code="QA09",
                severity="WARN",
                message=f"PO total (${supplier.po_draft.total:.2f}) meets or exceeds senior threshold (${senior_threshold:.2f})",
                source="rule",
            )
        )

    # QA10: chosen supplier != planned supplier
    if (
        supplier.supplier_id
        and plan.planned_supplier_id
        and supplier.supplier_id != plan.planned_supplier_id
    ):
        findings.append(
            Finding(
                code="QA10",
                severity="WARN",
                message=(
                    f"Chosen supplier ({supplier.supplier_id}) differs from "
                    f"planned supplier ({plan.planned_supplier_id})"
                ),
                source="rule",
            )
        )

    # QA11: email contains an amount other than PO unit cost or total
    if supplier.email and supplier.po_draft:
        body = supplier.email.body
        # Extract dollar amounts e.g. $10.00, $2200
        found_amounts = re.findall(r"\$([0-9]+(?:\.[0-9]+)?)", body)
        valid_amounts = {
            round(supplier.po_draft.unit_cost, 2),
            round(supplier.po_draft.total, 2),
        }
        for amt_str in found_amounts:
            amt = round(float(amt_str), 2)
            if amt not in valid_amounts:
                findings.append(
                    Finding(
                        code="QA11",
                        severity="CRITICAL",
                        message=f"Email body quotes unauthorized dollar amount: ${amt:.2f}",
                        source="rule",
                    )
                )
                break

    # QA12: any message confidence < LOW_CONFIDENCE
    confidences = [forecast.confidence, plan.confidence, supplier.confidence]
    if any(c < low_confidence_threshold for c in confidences):
        min_c = min(confidences)
        findings.append(
            Finding(
                code="QA12",
                severity="WARN",
                message=f"Low model confidence ({min_c:.2f}) below threshold ({low_confidence_threshold:.2f})",
                source="rule",
            )
        )

    # QA13: untrusted note flagged
    if untrusted_note_flagged:
        findings.append(
            Finding(
                code="QA13",
                severity="WARN",
                message="Untrusted note contained flagged injection pattern",
                source="rule",
            )
        )

    # QA14: primary supplier is INSOLVENT or ON_HOLD and an alternate is used
    primary_sup = next((s for s in supplier_options if s.get("is_primary") == 1), None)
    if (
        primary_sup
        and primary_sup.get("status") in ("INSOLVENT", "ON_HOLD")
        and supplier.supplier_id
        and supplier.supplier_id != primary_sup.get("supplier_id")
    ):
        findings.append(
            Finding(
                code="QA14",
                severity="WARN",
                message=(
                    f"Primary supplier ({primary_sup.get('supplier_id')}) is "
                    f"{primary_sup.get('status')}; alternate supplier ({supplier.supplier_id}) was selected"
                ),
                source="rule",
            )
        )

    return findings


def merge_findings(
    rule_findings: list[Finding],
    llm_findings: list[Finding] | None = None,
) -> list[Finding]:
    """Merge rule-generated findings with LLM-generated findings.

    Crucial guarantee: Rule-generated findings can NEVER be removed or downgraded.
    """
    merged: list[Finding] = list(rule_findings)
    seen_codes = {f.code for f in rule_findings}

    if llm_findings:
        for f in llm_findings:
            if f.code not in seen_codes:
                merged.append(f)
                seen_codes.add(f.code)

    return merged
