"""Unit tests for LangSmith and local OpenTelemetry tracing integration (SPEC 14)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from supplychain.config import Settings
from supplychain.tracing import enable_langsmith, generate_trace_summary, record_local_trace


def test_enable_langsmith_disabled_by_default():
    """When langsmith_tracing is False, enable_langsmith returns False without doing anything."""
    settings = Settings(langsmith_tracing=False, langsmith_api_key=SecretStr("dummy_key"))
    result = enable_langsmith(settings)
    assert result is False


def test_enable_langsmith_without_api_key():
    """When langsmith_tracing is True but api key is empty, returns False."""
    settings = Settings(langsmith_tracing=True, langsmith_api_key=SecretStr(""))
    result = enable_langsmith(settings)
    assert result is False


def test_enable_langsmith_enabled_with_key():
    """When langsmith_tracing is True and api key is present, instruments OpenTelemetry."""
    settings = Settings(
        langsmith_tracing=True,
        langsmith_api_key=SecretStr("ls_test_key_12345"),
        langsmith_project="test-project",
    )

    with (
        patch("langsmith.integrations.otel.OtelSpanProcessor") as mock_processor,
        patch("opentelemetry.instrumentation.crewai.CrewAIInstrumentor") as mock_instrumentor,
        patch("supplychain.tracing._LANGSMITH_INSTRUMENTED", False),
    ):
        mock_inst_instance = MagicMock()
        mock_instrumentor.return_value = mock_inst_instance

        res = enable_langsmith(settings)
        assert res is True
        mock_processor.assert_called_once()
        mock_inst_instance.instrument.assert_called_once()


def test_record_local_trace(tmp_path: Path):
    """record_local_trace appends valid structured JSON lines."""
    log_file = tmp_path / "langsmith_traces.jsonl"

    span = record_local_trace(
        cycle_id="CYCLE-TEST-1",
        agent_name="Demand Forecaster",
        task_name="forecast_task",
        latency_s=0.45,
        prompt_tokens=120,
        completion_tokens=40,
        total_tokens=160,
        status="COMPLETED",
        metadata={"scenario": "S01"},
        trace_path=log_file,
    )

    assert span["cycle_id"] == "CYCLE-TEST-1"
    assert span["agent_name"] == "Demand Forecaster"
    assert span["total_tokens"] == 160
    assert log_file.exists()

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert loaded["cycle_id"] == "CYCLE-TEST-1"
    assert loaded["latency_s"] == 0.45


def test_generate_trace_summary(tmp_path: Path):
    """generate_trace_summary produces a markdown table of recorded spans."""
    log_file = tmp_path / "langsmith_traces.jsonl"
    summary_file = tmp_path / "trace_summary.md"

    record_local_trace(
        cycle_id="CYCLE-A",
        agent_name="Demand Forecaster",
        task_name="forecast_task",
        latency_s=0.2,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        trace_path=log_file,
    )
    record_local_trace(
        cycle_id="CYCLE-A",
        agent_name="Inventory Planner",
        task_name="plan_task",
        latency_s=0.3,
        prompt_tokens=110,
        completion_tokens=30,
        total_tokens=140,
        trace_path=log_file,
    )

    summary = generate_trace_summary(trace_path=log_file, summary_path=summary_file)
    assert summary_file.exists()
    assert "# Agent Execution Trace Summary" in summary
    assert "Demand Forecaster" in summary
    assert "Inventory Planner" in summary
    assert "CYCLE-A" in summary
    assert "Total Captured Cycles" in summary
