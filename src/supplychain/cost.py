"""Token tracking and cost budget guardrails (cost.py) per SPEC 13."""

from __future__ import annotations

from typing import Any

from crewai import Agent

from supplychain.config import get_settings
from supplychain.models import CostReport


class BudgetExceeded(Exception):
    """Raised when cumulative cycle cost exceeds the configured budget."""


def calculate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    price_input_per_m: float = 1.50,
    price_output_per_m: float = 7.50,
) -> float:
    """Calculate notional cost in USD based on input and output token counts."""
    input_cost = (prompt_tokens / 1_000_000.0) * price_input_per_m
    output_cost = (completion_tokens / 1_000_000.0) * price_output_per_m
    return round(input_cost + output_cost, 6)


class CostGuard:
    """Task callback for CrewAI checking cumulative cost between tasks.

    Raises BudgetExceeded when cumulative cycle cost strictly exceeds budget_usd.
    """

    def __init__(
        self,
        agents: list[Agent],
        budget_usd: float | None = None,
        price_input_per_m: float | None = None,
        price_output_per_m: float | None = None,
    ) -> None:
        settings = get_settings()
        self.agents = agents
        self.budget_usd = budget_usd if budget_usd is not None else settings.cost_budget_usd
        self.price_input_per_m = (
            price_input_per_m if price_input_per_m is not None else settings.price_input_per_m
        )
        self.price_output_per_m = (
            price_output_per_m if price_output_per_m is not None else settings.price_output_per_m
        )

    def __call__(self, task_output: Any) -> None:
        """Invoked after each CrewAI task finishes."""
        report = self.get_report()
        if report.total_usd > self.budget_usd:
            raise BudgetExceeded(
                f"Cycle cost ${report.total_usd:.4f} exceeded budget of ${self.budget_usd:.2f}"
            )

    def get_report(self) -> CostReport:
        """Compile a per-agent CostReport from agent LLM instances."""
        prompt_tokens: dict[str, int] = {}
        completion_tokens: dict[str, int] = {}
        usd: dict[str, float] = {}
        total_cost = 0.0

        for agent in self.agents:
            role = agent.role
            llm = agent.llm
            summary = (
                llm.get_token_usage_summary() if hasattr(llm, "get_token_usage_summary") else None
            )

            p_tok = getattr(summary, "prompt_tokens", 0) if summary else 0
            c_tok = getattr(summary, "completion_tokens", 0) if summary else 0

            agent_cost = calculate_cost(
                p_tok,
                c_tok,
                price_input_per_m=self.price_input_per_m,
                price_output_per_m=self.price_output_per_m,
            )

            prompt_tokens[role] = p_tok
            completion_tokens[role] = c_tok
            usd[role] = agent_cost
            total_cost += agent_cost

        return CostReport(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            usd=usd,
            total_usd=round(total_cost, 6),
            budget_usd=self.budget_usd,
            prices_used={
                "input_per_m": self.price_input_per_m,
                "output_per_m": self.price_output_per_m,
            },
        )
