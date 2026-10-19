"""Deterministic guardrail callbacks per SPEC 8 and 9.

Implements the contract: (True, output) passes, (False, 'message') retries.
Guarantees LLMs cannot lie about numbers or terms.
"""

import re
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError

from supplychain.models import (
    EscalationDecision,
    ForecastMessage,
    InventoryPlanMessage,
    QAReport,
    SupplierMessage,
)


def _get_model(task_output: Any, model_cls: type) -> Any:
    """Extract Pydantic model instance from TaskOutput or direct object."""
    pyd = getattr(task_output, "pydantic", None)
    if isinstance(pyd, model_cls):
        return pyd
    if isinstance(task_output, model_cls):
        return task_output
    raw = getattr(task_output, "raw", None) or str(task_output)
    if isinstance(raw, str):
        try:
            return model_cls.model_validate_json(raw)
        except (ValueError, TypeError, ValidationError):
            return task_output
    return task_output


def build_forecast_guardrail(facts: dict[str, Any]) -> Callable[[Any], tuple[bool, Any]]:
    """Build guardrail verifying forecast numbers and deterministic flags."""

    def guardrail(task_output: Any) -> tuple[bool, Any]:
        msg = _get_model(task_output, ForecastMessage)
        if not isinstance(msg, ForecastMessage):
            return False, "Output must be a valid ForecastMessage"

        m_a = round(facts.get("method_a_daily", 0.0), 3)
        m_b = round(facts.get("method_b_daily", 0.0), 3)
        min_demand = 0.5 * min(m_a, m_b)
        max_demand = 2.0 * max(m_a, m_b, 1.0)

        # 1. Demand bounds check
        if not (min_demand <= round(msg.daily_demand_mean, 3) <= max_demand):
            return (
                False,
                f"daily_demand_mean ({msg.daily_demand_mean}) must be in [{min_demand:.3f}, {max_demand:.3f}]",
            )

        # 2. Number parity checks
        if round(msg.method_a_daily, 3) != m_a:
            return False, f"method_a_daily ({msg.method_a_daily}) must equal {m_a}"
        if round(msg.method_b_daily, 3) != m_b:
            return False, f"method_b_daily ({msg.method_b_daily}) must equal {m_b}"
        expected_cov = round(facts.get("data_coverage", 1.0), 3)
        if round(msg.data_coverage, 3) != expected_cov:
            return False, f"data_coverage ({msg.data_coverage}) must equal {expected_cov}"

        # 3. Deterministic flags check
        expected_flags = set(facts.get("expected_flags", []))
        for flag in expected_flags:
            if flag not in msg.flags:
                return False, f"Missing required deterministic flag: {flag}"

        return True, task_output

    return guardrail


def build_inventory_guardrail(facts: dict[str, Any]) -> Callable[[Any], tuple[bool, Any]]:
    """Build guardrail verifying inventory calculations against ground truth."""

    def guardrail(task_output: Any) -> tuple[bool, Any]:
        msg = _get_model(task_output, InventoryPlanMessage)
        if not isinstance(msg, InventoryPlanMessage):
            return False, "Output must be a valid InventoryPlanMessage"

        forecast_mean = round(facts.get("forecast_mean", 0.0), 3)
        if round(msg.daily_demand, 3) != forecast_mean:
            return (
                False,
                f"daily_demand ({msg.daily_demand}) must equal forecast mean ({forecast_mean})",
            )

        if msg.safety_stock != facts.get("expected_ss"):
            return False, f"safety_stock ({msg.safety_stock}) must equal {facts.get('expected_ss')}"

        if msg.reorder_point != facts.get("expected_rop"):
            return (
                False,
                f"reorder_point ({msg.reorder_point}) must equal {facts.get('expected_rop')}",
            )

        if msg.target_level != facts.get("expected_target"):
            return (
                False,
                f"target_level ({msg.target_level}) must equal {facts.get('expected_target')}",
            )

        if msg.needed_qty != facts.get("expected_needed"):
            return False, f"needed_qty ({msg.needed_qty}) must equal {facts.get('expected_needed')}"

        return True, task_output

    return guardrail


def build_supplier_guardrail(facts: dict[str, Any]) -> Callable[[Any], tuple[bool, Any]]:
    """Build guardrail verifying supplier selection, quantities, totals, and email content."""

    def guardrail(task_output: Any) -> tuple[bool, Any]:
        msg = _get_model(task_output, SupplierMessage)
        if not isinstance(msg, SupplierMessage):
            return False, "Output must be a valid SupplierMessage"

        if msg.po_draft is None:
            return True, task_output

        po = msg.po_draft
        eligible_ids = facts.get("eligible_ids", [])
        if po.supplier_id not in eligible_ids:
            return False, f"Chosen supplier {po.supplier_id} is not an eligible supplier"

        # Quantity check
        expected_qty = facts.get("expected_qty_by_sup", {}).get(po.supplier_id)
        if expected_qty is not None and po.qty != expected_qty:
            return False, f"PO quantity ({po.qty}) must equal recomputed quantity ({expected_qty})"

        # Unit cost and total check
        expected_cost = facts.get("unit_cost_by_sup", {}).get(po.supplier_id)
        if expected_cost is not None and round(po.unit_cost, 2) != round(expected_cost, 2):
            return False, f"PO unit cost ({po.unit_cost}) must equal {expected_cost}"

        expected_total = round(po.qty * po.unit_cost, 2)
        if round(po.total, 2) != expected_total:
            return False, f"PO total ({po.total}) must equal qty * unit_cost ({expected_total})"

        # Delivery date check
        as_of = facts.get("as_of_date", date.today())
        lt = facts.get("lead_time_by_sup", {}).get(po.supplier_id, 7)
        min_delivery = as_of + timedelta(days=lt)
        if po.requested_delivery_date < min_delivery:
            return (
                False,
                f"requested_delivery_date ({po.requested_delivery_date}) must be on or after {min_delivery}",
            )

        # Email checks
        if msg.email:
            body = msg.email.body
            if "http://" in body or "https://" in body:
                return False, "Email body must not contain external URLs"

            amounts = re.findall(r"\$([0-9]+(?:\.[0-9]+)?)", body)
            valid_amounts = {round(po.unit_cost, 2), round(po.total, 2)}
            for amt_str in amounts:
                amt = round(float(amt_str), 2)
                if amt not in valid_amounts:
                    return False, f"Email quotes unauthorized amount: ${amt:.2f}"

        return True, task_output

    return guardrail


def build_qa_guardrail(facts: dict[str, Any]) -> Callable[[Any], tuple[bool, Any]]:
    """Build guardrail verifying all deterministic QA findings are included and verdict is valid."""

    def guardrail(task_output: Any) -> tuple[bool, Any]:
        msg = _get_model(task_output, QAReport)
        if not isinstance(msg, QAReport):
            return False, "Output must be a valid QAReport"

        reported_codes = {f.code for f in msg.findings}
        required_codes = set(facts.get("required_rule_codes", []))

        missing_codes = required_codes - reported_codes
        if missing_codes:
            return (
                False,
                f"QA report is missing mandatory rule findings: {', '.join(sorted(missing_codes))}",
            )

        worst_severity = facts.get("worst_severity", "INFO")
        if worst_severity == "CRITICAL" and msg.verdict != "FAIL":
            return (
                False,
                f"Verdict must be FAIL when CRITICAL findings are present (got {msg.verdict})",
            )
        if worst_severity == "WARN" and msg.verdict == "PASS":
            return (
                False,
                f"Verdict cannot be PASS when WARN findings are present (got {msg.verdict})",
            )

        return True, task_output

    return guardrail


def build_escalation_guardrail(
    facts: dict[str, Any] | None = None,
) -> Callable[[Any], tuple[bool, Any]]:
    """Build guardrail verifying escalation decision level validity."""

    def guardrail(task_output: Any) -> tuple[bool, Any]:
        msg = _get_model(task_output, EscalationDecision)
        if not isinstance(msg, EscalationDecision):
            return False, "Output must be a valid EscalationDecision"

        if msg.level not in ("STANDARD", "SENIOR", "BLOCKED"):
            return False, f"Invalid escalation level: {msg.level}"

        return True, task_output

    return guardrail
