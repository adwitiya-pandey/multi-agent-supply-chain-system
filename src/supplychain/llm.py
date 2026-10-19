"""LLM factory for Gemini 3.8 Flash (live) and ScriptedLLM (offline) per SPEC 18."""

from __future__ import annotations

from typing import Any

from crewai import LLM
from crewai.llms.base_llm import BaseLLM

from supplychain.config import get_settings
from supplychain.scripted import ScriptedLLM


def get_llm(
    role: str = "",
    mode: str | None = None,
    replies: list[str] | None = None,
    context: dict[str, Any] | None = None,
    fault_mode: str | None = None,
) -> BaseLLM | LLM:
    """Construct an LLM instance for an agent.

    - If mode is 'gemini', constructs crewai.LLM with native Gemini provider.
    - Otherwise, returns deterministic ScriptedLLM (offline).
    """
    settings = get_settings()
    selected_mode = mode or settings.llm_mode

    if selected_mode == "gemini":
        key = settings.gemini_api_key.get_secret_value() or "dummy"
        return LLM(
            model=f"gemini/{settings.gemini_model}",
            api_key=key,
            max_rpm=settings.gemini_max_rpm,
        )

    # Scripted / Oracle mode
    scripted_mode = (
        "replies"
        if replies is not None
        else ("oracle" if selected_mode == "scripted" else selected_mode)
    )
    return ScriptedLLM(
        replies=replies,
        mode=scripted_mode,
        agent_role=role,
        context=context,
        fault_mode=fault_mode,
    )
