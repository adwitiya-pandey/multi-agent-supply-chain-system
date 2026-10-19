"""Tests for ScriptedLLM (scripted.py)."""

from crewai import Agent, Crew, Process, Task
from crewai.tools import tool
from pydantic import BaseModel

from supplychain.scripted import ScriptedLLM


class StockOutput(BaseModel):
    on_hand: int


CALLED_SKUS = []


@tool("check_stock_tool")
def check_stock_tool(sku: str) -> str:
    """Check stock level for SKU."""
    CALLED_SKUS.append(sku)
    return '{"on_hand": 42}'


def test_scripted_llm_drives_one_agent_crew_with_react_tool():
    CALLED_SKUS.clear()
    replies = [
        'Thought: Need stock.\nAction: check_stock_tool\nAction Input: {"sku": "SKU0001"}',
        'Thought: Have stock.\nFinal Answer: {"on_hand": 42}',
    ]
    llm = ScriptedLLM(replies=replies, mode="replies")
    agent = Agent(
        role="Inventory Clerk",
        goal="Check stock",
        backstory="Auditor",
        llm=llm,
        tools=[check_stock_tool],
        allow_delegation=False,
        max_iter=4,
    )
    task = Task(
        description="Verify stock for SKU0001",
        expected_output="JSON stock count",
        agent=agent,
        output_pydantic=StockOutput,
    )
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, tracing=False)
    result = crew.kickoff()

    assert result.pydantic.on_hand == 42
    assert CALLED_SKUS == ["SKU0001"]

    # Verify per-instance token usage tracking
    summary = llm.get_token_usage_summary()
    assert summary.total_tokens > 0
    assert summary.prompt_tokens > 0
    assert summary.completion_tokens > 0
