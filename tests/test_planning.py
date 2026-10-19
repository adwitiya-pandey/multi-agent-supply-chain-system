"""Tests for deterministic planning and inventory math (planning.py)."""

import math

from supplychain.planning import (
    DELAY_PENALTY_DAYS,
    calculate_coverage,
    calculate_method_a,
    calculate_method_b,
    calculate_reorder_plan,
    calculate_safety_stock,
    filter_eligible_suppliers,
    is_conflict,
    is_demand_spike,
    round_to_supplier_pack,
)


def test_method_a_constant():
    # 28 days of 10 -> mean = 10.0
    sales = [10] * 28
    assert calculate_method_a(sales) == 10.0


def test_method_a_varying():
    # 14 days of 10, 14 days of 20 -> (14*10 + 14*20) / 28 = 420 / 28 = 15.0
    sales = [10] * 14 + [20] * 14
    assert calculate_method_a(sales) == 15.0


def test_method_b_constant():
    # 56 days of 10 -> flat line at 10.0, next 14 days mean = 10.0
    sales = [10] * 56
    assert calculate_method_b(sales) == 10.0


def test_method_b_linear_trend():
    # y = x + 1 for x = 0..55 (56 points).
    # Next 14 days are x = 56..69.
    # Mean of x in 56..69 is (56 + 69) / 2 = 62.5.
    # Projected y = 62.5 + 1 = 63.5.
    sales = [i + 1 for i in range(56)]
    assert math.isclose(calculate_method_b(sales), 63.5, rel_tol=1e-5)


def test_method_b_floored_at_zero():
    # Steep downward trend going negative in future
    # Points: 56, 55, ..., 1. Next 14 points would be 0, -1, -2...
    sales = [max(1, 56 - i) for i in range(56)]
    result = calculate_method_b(sales)
    assert result >= 0.0


def test_conflict_detection():
    # abs(10 - 15) / max(10, 15, 1) = 5 / 15 = 0.333 > 0.30 -> conflict True
    assert is_conflict(10.0, 15.0) is True
    # abs(10 - 12) / max(10, 12, 1) = 2 / 12 = 0.1667 <= 0.30 -> conflict False
    assert is_conflict(10.0, 12.0) is False
    # Exactly on 0.30 boundary: abs(10 - 13) / 13 = 3 / 13 = 0.2307 <= 0.30 -> False
    assert is_conflict(10.0, 13.0) is False


def test_demand_spike():
    # Last 7 days = 20, prior 49 days = 10.
    # mean_last_7 = 20, mean_prior = 10.
    # 20 >= 2 * 10 and 10 > 0 -> True
    sales = [10] * 49 + [20] * 7
    assert is_demand_spike(sales) is True

    # Last 7 days = 19, prior 49 days = 10.
    # 19 < 2 * 10 -> False
    sales_no_spike = [10] * 49 + [19] * 7
    assert is_demand_spike(sales_no_spike) is False


def test_coverage():
    # 56 / 56 = 1.0
    assert calculate_coverage(56, 56) == 1.0
    # 44 / 56 = 0.7857 (< 0.80)
    assert math.isclose(calculate_coverage(44, 56), 44 / 56, rel_tol=1e-5)


def test_safety_stock_hand_computed():
    # Arithmetic:
    # d = 10.0, sd = 2.0, LT = 7, sLT = 1.0, service_level = 0.95
    # z = NormalDist().inv_cdf(0.95) = 1.6448536...
    # variance = 7 * (2^2) + (10^2) * (1^2) = 7*4 + 100*1 = 28 + 100 = 128
    # sqrt(128) = 11.3137085...
    # z * sqrt(128) = 1.6448536269514722 * 11.31370849898476 = 18.6094038...
    # ceil(18.6094038) = 19
    ss = calculate_safety_stock(
        d=10.0, sd=2.0, lead_time_days=7, lead_time_std=1.0, service_level=0.95
    )
    assert ss == 19


def test_safety_stock_zero_variability():
    # sd = 0, sLT = 0 -> SS must be 0
    ss = calculate_safety_stock(
        d=10.0, sd=0.0, lead_time_days=7, lead_time_std=0.0, service_level=0.95
    )
    assert ss == 0


def test_reorder_plan_hand_computed_order():
    # Arithmetic:
    # d = 10.0, sd = 2.0, LT = 7, sLT = 1.0, service_level = 0.95
    # SS = 19
    # ROP = ceil(10.0 * 7) + 19 = 70 + 19 = 89
    # on_hand = 50, on_order = 0 -> position = 50 <= 89 -> Order!
    # R = 7
    # target = 89 + ceil(10.0 * 7) = 89 + 70 = 159
    # needed = 159 - 50 = 109
    # urgency: on_hand / d = 50 / 10 = 5.0 < LT(7) -> EXPEDITE
    plan = calculate_reorder_plan(
        on_hand=50,
        on_order=0,
        daily_demand=10.0,
        daily_demand_std=2.0,
        lead_time_days=7,
        lead_time_std=1.0,
        service_level=0.95,
    )
    assert plan["safety_stock"] == 19
    assert plan["reorder_point"] == 89
    assert plan["target_level"] == 159
    assert plan["needed_qty"] == 109
    assert plan["action"] == "ORDER"
    assert plan["urgency"] == "EXPEDITE"


def test_reorder_plan_no_action_overstock():
    # position = 120 > ROP(89) -> NO_ACTION, needed = 0, urgency = NORMAL (120/10 = 12 >= 7)
    plan = calculate_reorder_plan(
        on_hand=120,
        on_order=0,
        daily_demand=10.0,
        daily_demand_std=2.0,
        lead_time_days=7,
        lead_time_std=1.0,
        service_level=0.95,
    )
    assert plan["action"] == "NO_ACTION"
    assert plan["needed_qty"] == 0
    assert plan["urgency"] == "NORMAL"


def test_supplier_rounding():
    # needed = 109, moq = 50, pack = 10 -> ceil(109/10)*10 = 110 >= 50 -> 110
    assert round_to_supplier_pack(needed=109, moq=50, pack_size=10) == 110

    # needed = 25, moq = 50, pack = 10 -> ceil(25/10)*10 = 30 < 50 -> 50 (MOQ applies)
    assert round_to_supplier_pack(needed=25, moq=50, pack_size=10) == 50

    # needed = 0 -> 0
    assert round_to_supplier_pack(needed=0, moq=50, pack_size=10) == 0


def test_filter_eligible_suppliers():
    suppliers = [
        {
            "supplier_id": "SUP001",
            "is_primary": 1,
            "status": "ACTIVE",
            "unit_cost": 20.0,
            "lead_time_days": 7,
        },
        {
            "supplier_id": "SUP002",
            "is_primary": 0,
            "status": "DELAYED",
            "unit_cost": 18.0,
            "lead_time_days": 8,
        },
        {
            "supplier_id": "SUP003",
            "is_primary": 0,
            "status": "INSOLVENT",
            "unit_cost": 15.0,
            "lead_time_days": 7,
        },
        {
            "supplier_id": "SUP004",
            "is_primary": 0,
            "status": "ON_HOLD",
            "unit_cost": 12.0,
            "lead_time_days": 7,
        },
    ]

    eligible = filter_eligible_suppliers(suppliers)
    assert len(eligible) == 2
    # Primary SUP001 first
    assert eligible[0]["supplier_id"] == "SUP001"
    assert eligible[0]["effective_lead_time"] == 7

    # Secondary SUP002 has DELAYED penalty (+7 days)
    assert eligible[1]["supplier_id"] == "SUP002"
    assert eligible[1]["effective_lead_time"] == 8 + DELAY_PENALTY_DAYS
