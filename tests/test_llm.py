"""Tests for LLM factory (llm.py)."""

from crewai.llms.base_llm import BaseLLM

from supplychain.llm import get_llm
from supplychain.scripted import ScriptedLLM


def test_get_llm_scripted():
    llm = get_llm(role="Demand Forecaster", mode="scripted")
    assert isinstance(llm, ScriptedLLM)
    assert llm.agent_role == "Demand Forecaster"


def test_get_llm_gemini_constructs_offline_no_network():
    # Constructing native Gemini provider with dummy key does not make network calls
    llm = get_llm(role="Inventory Planner", mode="gemini")
    assert isinstance(llm, BaseLLM)
    assert type(llm).__name__ == "GeminiCompletion"
    assert "gemini" in llm.model
