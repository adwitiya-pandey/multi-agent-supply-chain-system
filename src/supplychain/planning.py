"""Deterministic inventory and demand math using stdlib only.

All numbers, statistical estimates, safety stock, and reorder points are computed here.
Agents explain and structure decisions; they never compute these numbers.
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any

# Standard planning constants per SPEC 7
DELAY_PENALTY_DAYS: int = 7
REVIEW_PERIOD_DAYS: int = 7  # R = 7
DEFAULT_HORIZON_DAYS: int = 14
DEFAULT_SERVICE_LEVEL: float = 0.95


def calculate_method_a(sales_28: list[int]) -> float:
    """Method A: Mean of the last 28 days of daily sales units (zeros included)."""
    if not sales_28:
        return 0.0
    return sum(sales_28) / float(len(sales_28))


def calculate_method_b(sales_56: list[int]) -> float:
    """Method B: Mean over the next 14 days of a least-squares line fitted to the

    last 56 days, floored at 0 (hand-written, pure stdlib).
    """
    n = len(sales_56)
    if n == 0:
        return 0.0

    x_vals = list(range(n))
    y_vals = [float(v) for v in sales_56]

    x_bar = sum(x_vals) / float(n)
    y_bar = sum(y_vals) / float(n)

    denom = sum((x - x_bar) ** 2 for x in x_vals)
    if denom == 0:
        slope = 0.0
        intercept = y_bar
    else:
        num = sum((x_vals[i] - x_bar) * (y_vals[i] - y_bar) for i in range(n))
        slope = num / denom
        intercept = y_bar - slope * x_bar

    # Forecast next 14 days (indices n to n + 13), each floored at 0
    future_projections = [max(0.0, slope * (n + day) + intercept) for day in range(14)]
    return sum(future_projections) / 14.0


def is_conflict(method_a: float, method_b: float) -> bool:
    """Conflict detection: abs(a - b) / max(a, b, 1.0) > 0.30."""
    return abs(method_a - method_b) / max(method_a, method_b, 1.0) > 0.30


def is_demand_spike(sales_56: list[int]) -> bool:
    """Demand spike detection: mean(last 7 days) >= 2 * mean(days 8 to 56 back) and latter > 0."""
    if len(sales_56) < 8:
        return False

    recent_7 = sales_56[-7:]
    prior_days = sales_56[:-7]

    mean_recent = sum(recent_7) / float(len(recent_7))
    mean_prior = sum(prior_days) / float(len(prior_days))

    return mean_prior > 0 and mean_recent >= 2.0 * mean_prior


def calculate_coverage(days_with_data: int, total_days: int = 56) -> float:
    """Data coverage fraction over the window."""
    if total_days <= 0:
        return 0.0
    return days_with_data / float(total_days)


def calculate_safety_stock(
    d: float,
    sd: float,
    lead_time_days: float,
    lead_time_std: float,
    service_level: float = DEFAULT_SERVICE_LEVEL,
) -> int:
    """Safety stock formula with variable lead time:

    SS = ceil(z * sqrt(LT * sd^2 + d^2 * sLT^2))
    where z = NormalDist().inv_cdf(service_level).
    """
    if service_level <= 0.0 or service_level >= 1.0:
        raise ValueError(f"service_level must be in (0, 1), got {service_level}")

    z = NormalDist().inv_cdf(service_level)
    variance_term = lead_time_days * (sd**2) + (d**2) * (lead_time_std**2)
    if variance_term <= 0.0:
        return 0

    return math.ceil(z * math.sqrt(variance_term))


def calculate_reorder_plan(
    on_hand: int,
    on_order: int,
    daily_demand: float,
    daily_demand_std: float,
    lead_time_days: int,
    lead_time_std: float,
    service_level: float = DEFAULT_SERVICE_LEVEL,
    planned_supplier_id: str | None = None,
) -> dict[str, Any]:
    """Calculate deterministic inventory plan:

    ROP = ceil(d * LT) + SS
    target = ROP + ceil(d * R)
    needed = max(0, target - position) when position <= ROP, else 0
    """
    ss = calculate_safety_stock(
        daily_demand, daily_demand_std, lead_time_days, lead_time_std, service_level
    )
    rop = math.ceil(daily_demand * lead_time_days) + ss
    position = on_hand + on_order
    target = rop + math.ceil(daily_demand * REVIEW_PERIOD_DAYS)

    if position <= rop:
        action = "ORDER"
        needed = max(0, target - position)
    else:
        action = "NO_ACTION"
        needed = 0

    urgency = (
        "EXPEDITE"
        if (on_hand == 0 or (on_hand / max(daily_demand, 0.001)) < lead_time_days)
        else "NORMAL"
    )

    return {
        "on_hand": on_hand,
        "on_order": on_order,
        "daily_demand": daily_demand,
        "daily_demand_std": daily_demand_std,
        "lead_time_days": lead_time_days,
        "lead_time_std": lead_time_std,
        "service_level": service_level,
        "safety_stock": ss,
        "reorder_point": rop,
        "target_level": target,
        "needed_qty": needed,
        "action": action,
        "urgency": urgency,
        "planned_supplier_id": planned_supplier_id,
    }


def round_to_supplier_pack(needed: int, moq: int, pack_size: int) -> int:
    """Supplier rounding:

    qty = max(moq, ceil(needed / pack_size) * pack_size) when needed > 0, else 0.
    """
    if needed <= 0:
        return 0
    packed = math.ceil(needed / float(pack_size)) * pack_size
    return max(moq, packed)


def filter_eligible_suppliers(suppliers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter and rank eligible suppliers:

    - Status ACTIVE or DELAYED.
    - DELAYED adds DELAY_PENALTY_DAYS (7) to effective lead time.
    - INSOLVENT and ON_HOLD are excluded.
    - Ranked primary first (is_primary DESC), then lowest unit_cost ASC.
    """
    eligible: list[dict[str, Any]] = []
    for sup in suppliers:
        status = sup.get("status")
        if status not in ("ACTIVE", "DELAYED"):
            continue

        item = dict(sup)
        lt = int(item.get("lead_time_days", 7))
        if status == "DELAYED":
            item["effective_lead_time"] = lt + DELAY_PENALTY_DAYS
        else:
            item["effective_lead_time"] = lt

        eligible.append(item)

    # Sort primary first (1 before 0), then unit_cost ascending
    eligible.sort(key=lambda s: (-int(s.get("is_primary", 0)), float(s.get("unit_cost", 0.0))))
    return eligible
