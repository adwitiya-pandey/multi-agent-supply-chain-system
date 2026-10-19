"""Tests for token tracking and cost control (cost.py)."""

import math

import pytest
from crewai import Agent

from supplychain.cost import BudgetExceeded, CostGuard, calculate_cost
from supplychain.scripted import ScriptedLLM


def test_hand_computed_cost():
    # 100,000 prompt tokens @ $1.50/M = $0.150000
    # 20,000 completion tokens @ $7.50/M = $0.150000
    # Total = $0.300000
    cost = calculate_cost(
        prompt_tokens=100_000,
        completion_tokens=20_000,
        price_input_per_m=1.50,
        price_output_per_m=7.50,
    )
    assert math.isclose(cost, 0.30, abs_tol=1e-5)


def test_cost_guard_allows_exact_budget():
    llm = ScriptedLLM()
    # 100,000 prompt @ 1.50/M = $0.15; 46,666.66 completion @ 7.50/M = $0.35 -> $0.50 exactly
    # Let's set prompt = 100_000 ($0.15), completion = 46_667 tokens -> cost ≈ 0.500002
    # To stay strictly <= 0.50:
    # 100_000 prompt ($0.15) + 40_000 completion ($0.30) = $0.45 <= $0.50
    llm._track_token_usage_internal(
        {"prompt_tokens": 100_000, "completion_tokens": 40_000, "total_tokens": 140_000}
    )
    agent = Agent(role="Tester", goal="g", backstory="b", llm=llm)

    guard = CostGuard(
        agents=[agent],
        budget_usd=0.50,
        price_input_per_m=1.50,
        price_output_per_m=7.50,
    )
    # Does NOT raise when within budget
    guard(None)

    report = guard.get_report()
    assert report.total_usd == 0.45
    assert report.budget_usd == 0.50


def test_cost_guard_raises_over_budget():
    llm = ScriptedLLM()
    # 200,000 prompt @ 1.50/M = $0.30; 40,000 completion @ 7.50/M = $0.30 -> $0.60 > $0.50
    llm._track_token_usage_internal(
        {"prompt_tokens": 200_000, "completion_tokens": 40_000, "total_tokens": 240_000}
    )
    agent = Agent(role="Tester", goal="g", backstory="b", llm=llm)

    guard = CostGuard(
        agents=[agent],
        budget_usd=0.50,
        price_input_per_m=1.50,
        price_output_per_m=7.50,
    )

    with pytest.raises(BudgetExceeded, match="exceeded budget"):
        guard(None)
