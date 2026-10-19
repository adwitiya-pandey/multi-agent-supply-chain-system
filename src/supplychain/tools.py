"""CrewAI tools with read-only database execution and sanitized note wrapping.

All tools return JSON strings and enforce strict Pydantic/regex argument validation.
"""

from __future__ import annotations

import json
import re
import statistics
from typing import Any

from crewai.tools import tool

from supplychain.db import (
    get_inventory,
    get_sales_window,
    get_signals,
)
from supplychain.db import (
    get_supplier_options as db_get_supplier_options,
)
from supplychain.models import (
    SKU_ID_PATTERN,
    WAREHOUSE_ID_PATTERN,
)
from supplychain.planning import (
    calculate_coverage,
    calculate_method_a,
    calculate_method_b,
    filter_eligible_suppliers,
    is_conflict,
    is_demand_spike,
    round_to_supplier_pack,
)
from supplychain.planning import (
    calculate_reorder_plan as plan_calc,
)
from supplychain.sanitize import sanitize_untrusted_text


def _validate_id(val: str, pattern: str, name: str) -> str | None:
    if not isinstance(val, str) or not re.fullmatch(pattern, val):
        return f"Invalid {name} format: {val!r}"
    return None


@tool("get_demand_stats")
def get_demand_stats(sku: str, wh: str) -> str:
    """Retrieve historical demand statistics, Method A and B projections, coverage, and flags."""
    err = _validate_id(sku, SKU_ID_PATTERN, "sku") or _validate_id(wh, WAREHOUSE_ID_PATTERN, "wh")
    if err:
        return json.dumps({"error": err})

    sales_rows = get_sales_window(sku, wh, days=56)
    if not sales_rows:
        return json.dumps({"error": f"Unknown SKU or no sales data found for {sku} in {wh}"})

    units_56 = [u for _, u in sales_rows]
    units_28 = units_56[-28:] if len(units_56) >= 28 else units_56

    method_a = calculate_method_a(units_28)
    method_b = calculate_method_b(units_56)
    coverage = calculate_coverage(len(units_56), total_days=56)
    conflict = is_conflict(method_a, method_b)
    spike = is_demand_spike(units_56)
    std_dev = statistics.stdev(units_56) if len(units_56) > 1 else 0.0

    flags: list[str] = []
    if conflict:
        flags.append("CONFLICT")
    if spike:
        flags.append("SPIKE")
    if coverage < 0.80:
        flags.append("LOW_COVERAGE")

    # Check recent market signals for promo
    signals = get_signals(sku)
    for sig in signals:
        if sig.get("kind") == "PROMO":
            flags.append("PROMO_ACTIVE")
            break

    result = {
        "sku": sku,
        "wh": wh,
        "daily_demand_mean": round(method_a, 3),
        "daily_demand_std": round(std_dev, 3),
        "method_a_daily": round(method_a, 3),
        "method_b_daily": round(method_b, 3),
        "data_coverage": round(coverage, 3),
        "conflict": conflict,
        "demand_spike": spike,
        "flags": flags,
    }
    return json.dumps(result)


@tool("get_market_signals")
def get_market_signals(sku: str) -> str:
    """Retrieve external market signals (promos, competitor notes) with untrusted note sanitization."""
    err = _validate_id(sku, SKU_ID_PATTERN, "sku")
    if err:
        return json.dumps({"error": err})

    signals = get_signals(sku)
    sanitized_signals: list[dict[str, Any]] = []
    for sig in signals:
        wrapped_note, flagged = sanitize_untrusted_text(sig.get("note", ""))
        sanitized_signals.append(
            {
                "signal_id": sig.get("signal_id"),
                "signal_date": sig.get("signal_date"),
                "kind": sig.get("kind"),
                "note": wrapped_note,
                "flagged": flagged,
            }
        )

    return json.dumps({"sku": sku, "signals": sanitized_signals})


@tool("get_inventory_position")
def get_inventory_position(sku: str, wh: str) -> str:
    """Retrieve current stock on-hand and on-order position."""
    err = _validate_id(sku, SKU_ID_PATTERN, "sku") or _validate_id(wh, WAREHOUSE_ID_PATTERN, "wh")
    if err:
        return json.dumps({"error": err})

    inv = get_inventory(sku, wh)
    return json.dumps(
        {"sku": sku, "wh": wh, "on_hand": inv["on_hand"], "on_order": inv["on_order"]}
    )


@tool("calculate_reorder_plan")
def calculate_reorder_plan(
    on_hand: int,
    on_order: int,
    daily_demand: float,
    daily_demand_std: float,
    lead_time_days: int,
    lead_time_std: float,
    service_level: float = 0.95,
    planned_supplier_id: str = "",
) -> str:
    """Compute safety stock, reorder point, target stock level, needed quantity, action, and urgency."""
    plan = plan_calc(
        on_hand=on_hand,
        on_order=on_order,
        daily_demand=daily_demand,
        daily_demand_std=daily_demand_std,
        lead_time_days=lead_time_days,
        lead_time_std=lead_time_std,
        service_level=service_level,
        planned_supplier_id=planned_supplier_id or None,
    )
    return json.dumps(plan)


@tool("get_supplier_options")
def get_supplier_options(sku: str) -> str:
    """Retrieve eligible ranked suppliers for a SKU with sanitized notes."""
    err = _validate_id(sku, SKU_ID_PATTERN, "sku")
    if err:
        return json.dumps({"error": err})

    all_sups = db_get_supplier_options(sku)
    eligible = filter_eligible_suppliers(all_sups)

    clean_sups: list[dict[str, Any]] = []
    for sup in eligible:
        wrapped_note, flagged = sanitize_untrusted_text(sup.get("notes", ""))
        clean_sups.append(
            {
                "supplier_id": sup["supplier_id"],
                "name": sup["name"],
                "status": sup["status"],
                "unit_cost": sup["unit_cost"],
                "moq": sup["moq"],
                "pack_size": sup["pack_size"],
                "lead_time_days": sup["effective_lead_time"],
                "lead_time_std": sup["lead_time_std"],
                "is_primary": sup["is_primary"],
                "notes": wrapped_note,
                "note_flagged": flagged,
            }
        )

    return json.dumps({"sku": sku, "suppliers": clean_sups})


@tool("run_consistency_checks")
def run_consistency_checks(
    po_qty: int,
    needed_qty: int,
    moq: int,
    pack_size: int,
    po_total: float,
    unit_cost: float,
) -> str:
    """Verify purchase order consistency against recomputed quantity and total."""
    expected_qty = round_to_supplier_pack(needed_qty, moq=moq, pack_size=pack_size)
    qty_matches = po_qty == expected_qty
    expected_total = round(po_qty * unit_cost, 2)
    total_matches = abs(po_total - expected_total) < 0.01

    findings: list[str] = []
    if not qty_matches:
        findings.append(f"QA03: PO qty ({po_qty}) != expected pack-rounded qty ({expected_qty})")
    if not total_matches:
        findings.append(
            f"QA03: PO total (${po_total:.2f}) != unit_cost * qty (${expected_total:.2f})"
        )

    return json.dumps(
        {
            "passed": len(findings) == 0,
            "expected_qty": expected_qty,
            "expected_total": expected_total,
            "findings": findings,
        }
    )
