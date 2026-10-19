"""LangSmith and local OpenTelemetry tracing integration (SPEC 14).

When LANGSMITH_TRACING=true and LANGSMITH_API_KEY is configured, enables
OpenTelemetry tracing to LangSmith per official LangSmith CrewAI documentation.
When LANGSMITH_API_KEY is not configured or tracing is disabled, provides
structured local trace logging to logs/langsmith_traces.jsonl and docs/trace_summary.md.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from supplychain.config import Settings, get_settings

logger = structlog.get_logger(__name__)

_LANGSMITH_INSTRUMENTED = False


def enable_langsmith(settings: Settings | None = None) -> bool:
    """Enable OpenTelemetry instrumentation for CrewAI routing traces to LangSmith.

    Follows the official LangSmith CrewAI OpenTelemetry documentation:
    https://docs.smith.langchain.com/how_to_guides/tracing/trace_crewai

    Only instruments when LANGSMITH_TRACING=true and a non-empty LANGSMITH_API_KEY is set.
    Otherwise returns False without making any network calls or altering state.
    """
    global _LANGSMITH_INSTRUMENTED
    cfg = settings or get_settings()

    if not cfg.langsmith_tracing:
        logger.debug("langsmith_tracing_disabled")
        return False

    api_key = cfg.langsmith_api_key.get_secret_value() if cfg.langsmith_api_key else ""
    if not api_key.strip():
        logger.debug("langsmith_tracing_missing_api_key")
        return False

    if _LANGSMITH_INSTRUMENTED:
        return True

    try:
        from langsmith.integrations.otel import OtelSpanProcessor
        from opentelemetry import trace
        from opentelemetry.instrumentation.crewai import CrewAIInstrumentor
        from opentelemetry.sdk.trace import TracerProvider

        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_API_KEY"] = api_key
        os.environ["LANGSMITH_PROJECT"] = cfg.langsmith_project
        os.environ["OTEL_SDK_DISABLED"] = "false"

        current_provider = trace.get_tracer_provider()
        if isinstance(current_provider, TracerProvider):
            tracer_provider = current_provider
        else:
            tracer_provider = TracerProvider()
            trace.set_tracer_provider(tracer_provider)

        tracer_provider.add_span_processor(OtelSpanProcessor())
        CrewAIInstrumentor().instrument(tracer_provider=tracer_provider)
        _LANGSMITH_INSTRUMENTED = True
        logger.info("langsmith_tracing_enabled", project=cfg.langsmith_project)
        return True
    except (RuntimeError, ImportError, ValueError, TypeError) as exc:
        logger.warning("langsmith_instrumentation_failed", error=str(exc))
        return False


def record_local_trace(
    cycle_id: str,
    agent_name: str,
    task_name: str,
    latency_s: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    status: str = "COMPLETED",
    metadata: dict[str, Any] | None = None,
    trace_path: Path | str = "logs/langsmith_traces.jsonl",
) -> dict[str, Any]:
    """Record a structured trace span locally when external LangSmith is offline.

    Writes append-only JSONL entries capturing agent cycle execution metrics.
    """
    p = Path(trace_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    span = {
        "timestamp": datetime.now(UTC).isoformat(),
        "cycle_id": cycle_id,
        "agent_name": agent_name,
        "task_name": task_name,
        "status": status,
        "latency_s": round(latency_s, 4),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "metadata": metadata or {},
    }

    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(span) + "\n")

    return span


def generate_trace_summary(
    trace_path: Path | str = "logs/langsmith_traces.jsonl",
    summary_path: Path | str = "docs/trace_summary.md",
) -> str:
    """Read local trace logs and compile an executive markdown summary."""
    p = Path(trace_path)
    out_p = Path(summary_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if not p.exists():
        content = "# Local Agent Trace Summary\n\nNo trace entries recorded yet.\n"
        out_p.write_text(content, encoding="utf-8")
        return content

    spans: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    spans.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    cycles: dict[str, list[dict[str, Any]]] = {}
    for s in spans:
        cid = s.get("cycle_id", "unknown")
        cycles.setdefault(cid, []).append(s)

    lines = [
        "# Agent Execution Trace Summary",
        "",
        "Autonomous per-agent trace evidence recorded locally during pipeline runs.",
        "",
        f"**Total Captured Cycles**: {len(cycles)}  ",
        f"**Total Agent Spans**: {len(spans)}  ",
        "",
        "## Trace Breakdown by Cycle",
        "",
        "| Cycle ID | Agent | Task | Latency (s) | Prompt Tokens | Completion Tokens | Total Tokens | Status |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for cid, cycle_spans in cycles.items():
        for s in cycle_spans:
            lines.append(
                f"| `{cid}` | **{s.get('agent_name')}** | `{s.get('task_name')}` | "
                f"{s.get('latency_s', 0):.3f}s | {s.get('prompt_tokens', 0)} | "
                f"{s.get('completion_tokens', 0)} | {s.get('total_tokens', 0)} | {s.get('status')} |"
            )

    content = "\n".join(lines) + "\n"
    out_p.write_text(content, encoding="utf-8")
    return content
